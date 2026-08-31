variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "artisan-multiagent-ai"
}

variable "region" {
  description = "GCP Region for Cloud Run, Pub/Sub, and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "target_repo" {
  description = "Target GitHub repository in owner/name format"
  type        = string
  default     = "403errors/artisan-demo"
}

variable "github_repo_owner" {
  description = "GitHub repository owner organization or username"
  type        = string
  default     = "403errors"
}

variable "github_app_id" {
  description = "GitHub App ID"
  type        = string
  default     = "4744770"
}

variable "github_installation_id" {
  description = "GitHub App Installation ID"
  type        = string
  default     = "157129507"
}

variable "jira_url" {
  description = "Jira Cloud site URL"
  type        = string
  default     = "https://pieisnot22by7.atlassian.net"
}

variable "jira_username" {
  description = "Jira service account email address"
  type        = string
  default     = "pieisnot22by7@gmail.com"
}

variable "jira_project_key" {
  description = "Jira project key for tracking tickets"
  type        = string
  default     = "ART"
}

variable "orchestrator_image" {
  description = "Container image URI for orchestrator service"
  type        = string
  default     = "us-central1-docker.pkg.dev/artisan-multiagent-ai/cloud-run-source-deploy/orchestrator:latest"
}

variable "execution_sandbox_image" {
  description = "Container image URI for execution-sandbox Cloud Run job"
  type        = string
  default     = "us-central1-docker.pkg.dev/artisan-multiagent-ai/cloud-run-source-deploy/execution-sandbox:latest"
}

variable "dashboard_image" {
  description = "Container image URI for dashboard service"
  type        = string
  default     = "us-central1-docker.pkg.dev/artisan-multiagent-ai/cloud-run-source-deploy/dashboard:latest"
}
