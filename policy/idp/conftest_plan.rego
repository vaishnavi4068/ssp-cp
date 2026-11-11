package main

import data.idp.gcp.gcs_bucket
import rego.v1

# Conftest default package entrypoint (`conftest test plan.json -p policy/`)
deny contains msg if {
	some msg in gcs_bucket.deny
}
