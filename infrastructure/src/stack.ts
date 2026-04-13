import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import * as path from 'path';

export class AiProposalStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ── DynamoDB Tables ──────────────────────────────────────────────────────

    const draftTable = new dynamodb.Table(this, 'ProposalsDraftTable', {
      tableName: 'proposals_draft',
      partitionKey: { name: 'proposalId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const approvedTable = new dynamodb.Table(this, 'ProposalsApprovedTable', {
      tableName: 'proposals_approved',
      partitionKey: { name: 'proposalId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── S3 Bucket ─────────────────────────────────────────────────────────────

    const uploadBucket = new s3.Bucket(this, 'UploadsBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          maxAge: 3000,
        },
      ],
    });

    // ── SSM Parameter (Gemini API Key) ────────────────────────────────────────
    // Read at runtime via SSM to support SecureString type
    const geminiApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
      this,
      'GeminiApiKey',
      { parameterName: '/ai-proposal/gemini-api-key' },
    );

    // ── Lambda Functions ──────────────────────────────────────────────────────

    const generateLambda = new lambda.Function(this, 'GenerateLambda', {
      functionName: 'ai-proposal-generate',
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'generate.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../backend')),
      timeout: cdk.Duration.seconds(120),
      memorySize: 512,
      environment: {
        DRAFT_TABLE_NAME: draftTable.tableName,
        UPLOADS_BUCKET_NAME: uploadBucket.bucketName,
        GEMINI_API_KEY_PARAM: '/ai-proposal/gemini-api-key',
      },
    });

    const proposalsLambda = new lambda.Function(this, 'ProposalsLambda', {
      functionName: 'ai-proposal-proposals',
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'proposals.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../backend')),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        DRAFT_TABLE_NAME: draftTable.tableName,
        APPROVED_TABLE_NAME: approvedTable.tableName,
        UPLOADS_BUCKET_NAME: uploadBucket.bucketName,
      },
    });

    // ── IAM Grants ────────────────────────────────────────────────────────────

    // generate.py: R/W on proposals_draft, R/W on S3, invoke self async
    draftTable.grantReadWriteData(generateLambda);
    uploadBucket.grantReadWrite(generateLambda);
    geminiApiKeyParam.grantRead(generateLambda);
    // Allow the generate Lambda to invoke itself asynchronously (for Gemini async pattern)
    generateLambda.addToRolePolicy(new cdk.aws_iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [generateLambda.functionArn],
    }));

    // proposals.py: R/W on proposals_approved, R on proposals_draft, R/W on S3 (presigned URLs)
    approvedTable.grantReadWriteData(proposalsLambda);
    draftTable.grantReadWriteData(proposalsLambda);
    uploadBucket.grantReadWrite(proposalsLambda);

    // ── Cognito User Pool (Phase 2 ready — not attached as authorizer) ────────

    const userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: 'ai-proposal-user-pool',
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool,
      userPoolClientName: 'ai-proposal-web-client',
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
    });

    // ── API Gateway ───────────────────────────────────────────────────────────

    const corsOptions: apigateway.CorsOptions = {
      allowOrigins: apigateway.Cors.ALL_ORIGINS,
      allowMethods: apigateway.Cors.ALL_METHODS,
      allowHeaders: ['Content-Type', 'Authorization'],
    };

    const api = new apigateway.RestApi(this, 'AiProposalApi', {
      restApiName: 'ai-proposal-api',
      defaultCorsPreflightOptions: corsOptions,
      deployOptions: {
        stageName: 'prod',
      },
    });

    const generateIntegration = new apigateway.LambdaIntegration(generateLambda);
    const proposalsIntegration = new apigateway.LambdaIntegration(proposalsLambda);

    // POST /generate
    const generateResource = api.root.addResource('generate');
    generateResource.addMethod('POST', generateIntegration);

    // POST /approve
    const approveResource = api.root.addResource('approve');
    approveResource.addMethod('POST', proposalsIntegration);

    // POST /upload-url
    const uploadUrlResource = api.root.addResource('upload-url');
    uploadUrlResource.addMethod('POST', proposalsIntegration);

    // GET /proposals
    // GET /proposals/{id}
    const proposalsResource = api.root.addResource('proposals');
    proposalsResource.addMethod('GET', proposalsIntegration);

    const proposalByIdResource = proposalsResource.addResource('{id}');
    proposalByIdResource.addMethod('GET', proposalsIntegration);

    // ── Stack Outputs ─────────────────────────────────────────────────────────

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'API Gateway URL',
    });

    new cdk.CfnOutput(this, 'UploadsBucketName', {
      value: uploadBucket.bucketName,
      description: 'S3 uploads bucket name',
    });

    new cdk.CfnOutput(this, 'UserPoolId', {
      value: userPool.userPoolId,
      description: 'Cognito User Pool ID (Phase 2)',
    });
  }
}
