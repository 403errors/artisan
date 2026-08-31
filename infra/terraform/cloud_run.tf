# --- Orchestrator Cloud Run Service ---
resource "google_cloud_run_v2_service" "orchestrator" {
  name     = "orchestrator"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.orchestrator.email
    timeout         = "3600s"

    containers {
      image = var.orchestrator_image

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "ARTISAN_GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "ARTISAN_PUBSUB_TOPIC"
        value = google_pubsub_topic.github_events.name
      }
      env {
        name  = "ARTISAN_JIRA_URL"
        value = var.jira_url
      }
      env {
        name  = "ARTISAN_JIRA_USERNAME"
        value = var.jira_username
      }
      env {
        name  = "ARTISAN_JIRA_PROJECT_KEY"
        value = var.jira_project_key
      }
      env {
        name  = "ARTISAN_GITHUB_APP_ID"
        value = var.github_app_id
      }
      env {
        name  = "ARTISAN_GITHUB_INSTALLATION_ID"
        value = var.github_installation_id
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "ARTISAN_CLOUD_RUN_REGION"
        value = var.region
      }
      env {
        name  = "ARTISAN_EXECUTION_SANDBOX_JOB_NAME"
        value = "execution-sandbox"
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.orchestrator_roles
  ]
}

# Allow public webhook delivery to Orchestrator
resource "google_cloud_run_v2_service_iam_member" "orchestrator_public" {
  name     = google_cloud_run_v2_service.orchestrator.name
  location = var.region
  project  = var.project_id
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Execution Sandbox Cloud Run Job ---
resource "google_cloud_run_v2_job" "execution_sandbox" {
  name     = "execution-sandbox"
  location = var.region
  project  = var.project_id

  template {
    template {
      service_account = google_service_account.execution_sandbox.email
      timeout         = "1800s"
      max_retries     = 3

      containers {
        image = var.execution_sandbox_image

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }

        env {
          name  = "ARTISAN_GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "ARTISAN_GITHUB_APP_ID"
          value = var.github_app_id
        }
        env {
          name  = "ARTISAN_GITHUB_INSTALLATION_ID"
          value = var.github_installation_id
        }
        env {
          name  = "ARTISAN_CLOUD_RUN_REGION"
          value = var.region
        }
        env {
          name  = "ARTISAN_DEMO_REPO_TEST_COMMAND"
          value = "npm test"
        }
        env {
          name  = "GOOGLE_GENAI_USE_VERTEXAI"
          value = "TRUE"
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GOOGLE_CLOUD_LOCATION"
          value = "global"
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.execution_sandbox_roles
  ]
}

# --- Dashboard Cloud Run Service ---
resource "google_cloud_run_v2_service" "dashboard" {
  name     = "dashboard"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.dashboard.email
    timeout         = "300s"

    containers {
      image = var.dashboard_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "ARTISAN_TARGET_REPO"
        value = var.target_repo
      }
      env {
        name  = "ARTISAN_PUBSUB_TOPIC"
        value = google_pubsub_topic.github_events.name
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "AUTH_TRUST_HOST"
        value = "true"
      }

      env {
        name = "GITHUB_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.dashboard_oauth_client_id.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "GITHUB_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.dashboard_oauth_client_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "AUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.dashboard_auth_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_secret_manager_secret_iam_member.dashboard_client_id,
    google_secret_manager_secret_iam_member.dashboard_client_secret,
    google_secret_manager_secret_iam_member.dashboard_auth_secret
  ]
}

# Allow public web access to Dashboard
resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  name     = google_cloud_run_v2_service.dashboard.name
  location = var.region
  project  = var.project_id
  role     = "roles/run.invoker"
  member   = "allUsers"
}
