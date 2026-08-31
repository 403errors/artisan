resource "google_service_account" "orchestrator" {
  account_id   = "orchestrator"
  display_name = "Artisan Orchestrator Service Account"
  project      = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

resource "google_service_account" "execution_sandbox" {
  account_id   = "execution-sandbox"
  display_name = "Artisan Execution Sandbox Service Account"
  project      = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

resource "google_service_account" "dashboard" {
  account_id   = "dashboard"
  display_name = "Artisan Dashboard Service Account"
  project      = var.project_id

  depends_on = [google_project_service.enabled_apis]
}

resource "google_service_account" "github_actions_deployer" {
  account_id   = "github-actions-deployer"
  display_name = "GitHub Actions Deployer Service Account"
  project      = var.project_id

  depends_on = [google_project_service.enabled_apis]
}
