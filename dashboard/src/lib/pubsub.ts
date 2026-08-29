import { PubSub } from "@google-cloud/pubsub";

import { GCP_PROJECT_ID, PUBSUB_TOPIC } from "@/lib/config";

let client: PubSub | undefined;

function getPubSub(): PubSub {
  if (!client) {
    client = new PubSub({ projectId: GCP_PROJECT_ID });
  }
  return client;
}

export type ManualActionKind = "retry_gate1" | "retry_gate2" | "retry_gate3" | "escalate" | "mark_done";

export interface ManualActionEnvelope {
  kind: "manual_action";
  action_id: string;
  action: ManualActionKind;
  repo: string;
  issue_number: number;
  actor: string;
  reason?: string;
}

// Publishes to the same topic agents/'s real GitHub webhooks use — discriminated by `kind` on
// the agents-side decoder (gcp/pubsub.py::decode_push_message). Returns the Pub/Sub message id.
export async function publishManualAction(envelope: ManualActionEnvelope): Promise<string> {
  const topic = getPubSub().topic(PUBSUB_TOPIC);
  return topic.publishMessage({ json: envelope });
}
