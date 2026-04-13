import * as cdk from 'aws-cdk-lib';
import { AiProposalStack } from './stack';

const app = new cdk.App();

new AiProposalStack(app, 'AiProposalStack', {
  description: 'AI-Assisted Proposal & Document Intelligence Platform',
});

app.synth();
