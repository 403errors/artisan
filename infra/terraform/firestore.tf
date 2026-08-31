# Native Firestore database
resource "google_firestore_database" "database" {
  name        = "(default)"
  project     = var.project_id
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled_apis]
}

# Index: tickets (github_repo ASC, updated_at DESC)
resource "google_firestore_index" "tickets_repo_updated_at" {
  project    = var.project_id
  database   = google_firestore_database.database.name
  collection = "tickets"

  fields {
    field_path = "github_repo"
    order      = "ASCENDING"
  }

  fields {
    field_path = "updated_at"
    order      = "DESCENDING"
  }
}

# Index: tickets (github_repo ASC, status ASC, updated_at DESC)
resource "google_firestore_index" "tickets_repo_status_updated_at" {
  project    = var.project_id
  database   = google_firestore_database.database.name
  collection = "tickets"

  fields {
    field_path = "github_repo"
    order      = "ASCENDING"
  }

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }

  fields {
    field_path = "updated_at"
    order      = "DESCENDING"
  }
}
