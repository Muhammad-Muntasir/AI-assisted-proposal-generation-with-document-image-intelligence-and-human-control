import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { AiProposalStack } from '../src/stack';

/**
 * CDK assertion tests for AiProposalStack
 * Validates: Requirements 7.1, 7.2, 7.5, 7.6
 */

let template: Template;

beforeAll(() => {
  const app = new cdk.App();
  const stack = new AiProposalStack(app, 'TestAiProposalStack');
  template = Template.fromStack(stack);
});

// ── Lambda Functions ──────────────────────────────────────────────────────────

describe('Lambda functions', () => {
  test('exactly 2 Lambda functions are provisioned', () => {
    template.resourceCountIs('AWS::Lambda::Function', 2);
  });

  test('generate Lambda uses Python 3.11 runtime', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'ai-proposal-generate',
      Runtime: 'python3.11',
      Handler: 'generate.handler',
    });
  });

  test('proposals Lambda uses Python 3.11 runtime', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'ai-proposal-proposals',
      Runtime: 'python3.11',
      Handler: 'proposals.handler',
    });
  });

  test('generate Lambda has GEMINI_API_KEY environment variable', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'ai-proposal-generate',
      Environment: {
        Variables: Match.objectLike({
          GEMINI_API_KEY: Match.anyValue(),
          DRAFT_TABLE_NAME: Match.anyValue(),
          UPLOADS_BUCKET_NAME: Match.anyValue(),
        }),
      },
    });
  });

  test('proposals Lambda does NOT have GEMINI_API_KEY', () => {
    const functions = template.findResources('AWS::Lambda::Function', {
      Properties: {
        FunctionName: 'ai-proposal-proposals',
      },
    });
    const proposalsFn = Object.values(functions)[0] as any;
    const envVars = proposalsFn?.Properties?.Environment?.Variables ?? {};
    expect(envVars).not.toHaveProperty('GEMINI_API_KEY');
  });
});

// ── DynamoDB Tables ───────────────────────────────────────────────────────────

describe('DynamoDB tables', () => {
  test('exactly 2 DynamoDB tables are provisioned', () => {
    template.resourceCountIs('AWS::DynamoDB::Table', 2);
  });

  test('proposals_draft table has proposalId as partition key', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'proposals_draft',
      KeySchema: [{ AttributeName: 'proposalId', KeyType: 'HASH' }],
      BillingMode: 'PAY_PER_REQUEST',
    });
  });

  test('proposals_approved table has proposalId as partition key', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'proposals_approved',
      KeySchema: [{ AttributeName: 'proposalId', KeyType: 'HASH' }],
      BillingMode: 'PAY_PER_REQUEST',
    });
  });
});

// ── S3 Bucket ─────────────────────────────────────────────────────────────────

describe('S3 bucket', () => {
  test('exactly 1 S3 bucket is provisioned', () => {
    template.resourceCountIs('AWS::S3::Bucket', 1);
  });

  test('S3 bucket blocks all public access', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });
});

// ── API Gateway ───────────────────────────────────────────────────────────────

describe('API Gateway', () => {
  test('exactly 1 RestApi is provisioned', () => {
    template.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  });

  test('API Gateway is named ai-proposal-api', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      Name: 'ai-proposal-api',
    });
  });
});

// ── IAM Boundaries ────────────────────────────────────────────────────────────

describe('IAM boundaries', () => {
  /**
   * generate.py must NOT have write access to proposals_approved.
   * We verify by checking that no IAM policy attached to the generate Lambda
   * role contains a statement granting dynamodb:PutItem / UpdateItem / DeleteItem
   * on the proposals_approved table ARN.
   */
  test('generate Lambda has no write permission on proposals_approved', () => {
    const policies = template.findResources('AWS::IAM::Policy');

    // Collect all policy documents attached to the generate Lambda role
    const generatePolicies = Object.values(policies).filter((policy: any) => {
      const statements: any[] = policy.Properties?.PolicyDocument?.Statement ?? [];
      return statements.some((stmt: any) => {
        const actions: string[] = Array.isArray(stmt.Action)
          ? stmt.Action
          : [stmt.Action];
        return actions.some((a) => a.includes('dynamodb'));
      });
    });

    // None of the generate Lambda's policies should reference proposals_approved with write actions
    const writeActions = [
      'dynamodb:PutItem',
      'dynamodb:UpdateItem',
      'dynamodb:DeleteItem',
      'dynamodb:BatchWriteItem',
    ];

    for (const policy of generatePolicies) {
      const statements: any[] = (policy as any).Properties?.PolicyDocument?.Statement ?? [];
      for (const stmt of statements) {
        const actions: string[] = Array.isArray(stmt.Action)
          ? stmt.Action
          : [stmt.Action];
        const hasWrite = actions.some((a) => writeActions.includes(a));
        if (!hasWrite) continue;

        // Check if this statement targets proposals_approved
        const resources: any[] = Array.isArray(stmt.Resource)
          ? stmt.Resource
          : [stmt.Resource];
        const targetsApproved = resources.some((r: any) => {
          const str = JSON.stringify(r);
          return str.includes('proposals_approved');
        });

        // If this policy grants write on approved table, it must NOT be the generate Lambda's policy
        // We check by ensuring the policy logical ID doesn't contain "Generate"
        const policyEntry = Object.entries(policies).find(
          ([, v]) => v === policy,
        );
        if (targetsApproved && policyEntry) {
          expect(policyEntry[0]).not.toMatch(/Generate/i);
        }
      }
    }
  });

  /**
   * proposals.py must NOT have write access to proposals_draft.
   * The proposals Lambda only gets grantReadData on the draft table.
   */
  test('proposals Lambda has no write permission on proposals_draft', () => {
    const policies = template.findResources('AWS::IAM::Policy');

    const writeActions = [
      'dynamodb:PutItem',
      'dynamodb:UpdateItem',
      'dynamodb:DeleteItem',
      'dynamodb:BatchWriteItem',
    ];

    for (const [logicalId, policy] of Object.entries(policies)) {
      // Only look at policies associated with the proposals Lambda role
      if (!logicalId.includes('Proposals')) continue;

      const statements: any[] = (policy as any).Properties?.PolicyDocument?.Statement ?? [];
      for (const stmt of statements) {
        const actions: string[] = Array.isArray(stmt.Action)
          ? stmt.Action
          : [stmt.Action];
        const hasWrite = actions.some((a) => writeActions.includes(a));
        if (!hasWrite) continue;

        const resources: any[] = Array.isArray(stmt.Resource)
          ? stmt.Resource
          : [stmt.Resource];
        const targetsApproved = resources.some((r: any) => {
          const str = JSON.stringify(r);
          return str.includes('proposals_draft');
        });

        expect(targetsApproved).toBe(false);
      }
    }
  });
});

// ── Cognito ───────────────────────────────────────────────────────────────────

describe('Cognito', () => {
  test('Cognito User Pool is provisioned', () => {
    template.resourceCountIs('AWS::Cognito::UserPool', 1);
  });

  test('Cognito User Pool is NOT attached as API Gateway authorizer', () => {
    // There should be no AWS::ApiGateway::Authorizer resource
    const authorizers = template.findResources('AWS::ApiGateway::Authorizer');
    expect(Object.keys(authorizers)).toHaveLength(0);
  });
});
