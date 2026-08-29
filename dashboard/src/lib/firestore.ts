import { Firestore } from "@google-cloud/firestore";

import { GCP_PROJECT_ID } from "@/lib/config";

let client: Firestore | undefined;

// Singleton, mirroring agents/'s own `@lru_cache(maxsize=1)` pattern — one client per process,
// relying on ADC exactly like the Python services (no service-account key file convention exists
// anywhere in this repo). Default Firestore database, no `databaseId` — matches agents/.
export function getFirestore(): Firestore {
  if (!client) {
    client = new Firestore({ projectId: GCP_PROJECT_ID });
  }
  return client;
}
