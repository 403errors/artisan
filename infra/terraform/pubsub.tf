# --- Dead Letter Queue Topic ---
resource "google_pubsub_topic" "github_events_dlq" {
  name    = "artisan-github-events-dlq"
  project = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

# --- Main Events Topic ---
resource "google_pubsub_topic" "github_events" {
  name    = "artisan-github-events"
  project = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

# Allow dashboard to publish manual action events to the main topic
resource "google_pubsub_topic_iam_member" "dashboard_publisher" {
  topic   = google_pubsub_topic.github_events.name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.dashboard.email}"
}

# Allow orchestrator to publish events to the main topic
resource "google_pubsub_topic_iam_member" "orchestrator_publisher" {
  topic   = google_pubsub_topic.github_events.name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.orchestrator.email}"
}

# Allow Pub/Sub service agent to publish to the DLQ topic
resource "google_pubsub_topic_iam_member" "pubsub_agent_dlq_publisher" {
  topic   = google_pubsub_topic.github_events_dlq.name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# --- Push Subscription ---
resource "google_pubsub_subscription" "github_events_push" {
  name    = "artisan-github-events-push"
  project = var.project_id
  topic   = google_pubsub_topic.github_events.name

  ack_deadline_seconds = 600

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.orchestrator.uri}/pubsub/push"

    oidc_token {
      service_account_email = google_service_account.orchestrator.email
      audience              = "${google_cloud_run_v2_service.orchestrator.uri}/pubsub/push"
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.github_events_dlq.id
    max_delivery_attempts = 5
  }

  depends_on = [
    google_pubsub_topic_iam_member.pubsub_agent_dlq_publisher,
    google_service_account_iam_member.pubsub_token_creator
  ]
}

# Allow Pub/Sub service agent to acknowledge messages on the push subscription
resource "google_pubsub_subscription_iam_member" "pubsub_agent_subscriber" {
  subscription = google_pubsub_subscription.github_events_push.name
  project      = var.project_id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
