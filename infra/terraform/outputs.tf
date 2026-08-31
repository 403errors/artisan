output "orchestrator_url" {
  description = "Cloud Run URL for the Orchestrator service"
  value       = google_cloud_run_v2_service.orchestrator.uri
}

output "dashboard_url" {
  description = "Cloud Run URL for the Dashboard service"
  value       = google_cloud_run_v2_service.dashboard.uri
}

output "pubsub_topic" {
  description = "Pub/Sub topic for GitHub webhook events"
  value       = google_pubsub_topic.github_events.name
}

output "pubsub_subscription" {
  description = "Pub/Sub push subscription name"
  value       = google_pubsub_subscription.github_events_push.name
}

output "workload_identity_provider" {
  description = "Full resource name of the Workload Identity Provider for GitHub Actions"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Email of the GitHub Actions deployer service account"
  value       = google_service_account.github_actions_deployer.email
}
