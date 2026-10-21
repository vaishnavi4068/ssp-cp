package idp.policy_test

import data.idp.gcp.gcs_bucket
import data.idp.labels
import data.idp.naming
import rego.v1

# Canonical valid requested document matching `specs/examples/gcs_bucket.gates.json` (with APM12345 -> apm12345)
canonical_requested_doc := {
	"api_version": "idp.spp/v1",
	"kind": "gcs_bucket",
	"action": "create",
	"metadata": {
		"apm_id": "apm12345",
		"project_id": "<lob>-nonprod-orders-svc",
		"environment": "nonprod",
		"lob": "<lob>",
		"data_sensitivity": "restricted",
		"data_classification": "proprietary",
		"owner": "bucket.owner@example.com",
		"shared_mailbox": "<lob>-orders-team@example.com",
		"requested_by": "requester@example.com",
		"cost_center": "000000",
		"tenancy": "dedicated",
		"labels": {
			"app": "orders",
		},
		"extensions": {
			"<lob>": {
				"<lob>ml_version": "1.5",
			},
		},
	},
	"spec": {
		"name": "<lob>-nonprod-orders-landing-a1b2",
		"location": "us-east1",
		"storage_class": "STANDARD",
		"versioning": false,
		"lifecycle_rules": [],
		"access": [
			{
				"role": "roles/storage.objectAdmin",
				"members": [
					"serviceAccount:orders-pipeline@<lob>-nonprod-orders-svc.iam.gserviceaccount.com",
				],
			},
			{
				"role": "roles/storage.objectViewer",
				"members": [
					"group:gcp-<lob>-nonprod-orders-read@example.com",
				],
			},
		],
		"purpose": "Landing zone for order events",
	},
}

requested_input := {
	"stage": "requested",
	"cloud": "gcp",
	"app_alias": "orders",
	"resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
	"document": canonical_requested_doc,
}

approved_input := {
	"stage": "approved",
	"cloud": "gcp",
	"app_alias": "orders",
	"resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
	"document": canonical_requested_doc,
}

valid_plan_input := {
	"stage": "plan",
	"approved_delete_request": false,
	"resource_changes": [
		{
			"address": "module.gcs_bucket[\"<lob>-nonprod-orders-landing-a1b2\"].google_storage_bucket.this",
			"type": "google_storage_bucket",
			"change": {
				"actions": ["create"],
				"after": {
					"name": "<lob>-nonprod-orders-landing-a1b2",
					"location": "us-east1",
					"storage_class": "STANDARD",
					"uniform_bucket_level_access": true,
					"public_access_prevention": "enforced",
					"force_destroy": false,
					"default_kms_key_name": "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek",
					"retention_policy": {
						"retention_period": 7776000,
						"is_locked": false,
					},
					"soft_delete_policy": {
						"retention_duration_seconds": 604800,
					},
					"lifecycle_rules": [],
					"labels": {
						"app": "orders",
						"costcenter": "000000",
						"dataclassification": "proprietary",
						"datasensitivity": "restricted",
						"environmenttype": "nonprod",
						"idp_resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
						"owner": "bucket_owner_example_com",
						"primarylob": "<lob>",
						"provisionedby": "idp",
						"sharedemailaddress": "<lob>-orders-team_example_com",
						"sppappid": "apm12345",
						"tenancy": "dedicated",
					},
				},
			},
		},
	],
}

# 1. Valid requested stage passes
test_requested_valid_allow if {
	res := gcs_bucket.result with input as requested_input
	res.decision == "allow"
	count(res.violations) == 0
}

# 2. Valid approved stage returns allow_with_mutations and exact 10-entry guardrail_trace
test_approved_produces_10_guardrail_trace_entries if {
	res := gcs_bucket.result with input as approved_input
	res.decision == "allow_with_mutations"
	count(res.violations) == 0
	count(res.guardrail_trace) == 10
	rule_ids := [t.rule_id | some t in res.guardrail_trace]
	rule_ids == [
		"GCS-UBLA-001",
		"GCS-PAP-001",
		"GCS-ENC-001",
		"GCS-RET-001",
		"GCS-RET-003",
		"GCS-SDP-001",
		"GCS-DEL-001",
		"LBL-001",
		"PRQ-001",
		"PRQ-002",
	]
}

# 3. Verify 8 mandatory labels computed without environmentsubtype and with sppappid == apm12345
test_labels_computed_8_mandatory_no_environmentsubtype if {
	res := gcs_bucket.result with input as approved_input
	lbls := res.computed_labels
	not "environmentsubtype" in object.keys(lbls)
	lbls.sppappid == "apm12345"
	lbls.costcenter == "000000"
	lbls.environmenttype == "nonprod"
	lbls.primarylob == "<lob>"
	lbls.datasensitivity == "restricted"
	lbls.owner == "bucket_owner_example_com"
	lbls.provisionedby == "idp"
	lbls.idp_resource_id == "9478bcfc-c2cf-583b-8bd8-096476647840"
	lbls.sharedemailaddress == "<lob>-orders-team_example_com"
}

# 4. APM ID format check (`^APM\d{5}$` case-insensitive)
test_apm_id_case_insensitive_5_digits_valid if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/metadata/apm_id", "value": "APM12345"}])
	res := gcs_bucket.result with input as inp
	res.decision == "allow"
}

test_apm_id_7_digits_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/metadata/apm_id", "value": "apm0017299"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "NAM-APM-001"
}

test_apm_id_invalid_prefix_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/metadata/apm_id", "value": "APP12345"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "NAM-APM-001"
}

# 5. Naming rules: GCS-NAME-001, GCS-NAME-002, NAM-RSV-001, NAM-IMM-001, NAM-LEG-001
test_naming_env_mismatch_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "<lob>-prod-orders-landing-a1b2"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-NAME-001"
}

test_naming_missing_suffix_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "<lob>-nonprod-orders-landing"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-NAME-001"
}

test_naming_uppercase_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "<LOB>-nonprod-orders-landing-a1b2"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-NAME-001"
}

test_naming_google_substring_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "<lob>-nonprod-orders-google-a1b2"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-NAME-002"
}

test_naming_goog_prefix_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "goog-nonprod-orders-landing-a1b2"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-NAME-002"
}

test_naming_reserved_purpose_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/name", "value": "<lob>-nonprod-orders-restricted-a1b2"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "NAM-RSV-001"
}

test_naming_update_rename_rejected if {
	inp := object.union(
		json.patch(requested_input, [
			{"op": "replace", "path": "/document/action", "value": "update"},
			{"op": "replace", "path": "/document/spec/name", "value": "<lob>-nonprod-orders-newname-a1b2"},
		]),
		{"existing_name": "<lob>-nonprod-orders-landing-a1b2"},
	)
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "NAM-IMM-001"
}

test_naming_import_legacy_allowed_and_marks_label if {
	inp := json.patch(requested_input, [
		{"op": "replace", "path": "/document/action", "value": "import"},
		{"op": "replace", "path": "/document/spec/name", "value": "legacy-bucket-without-suffix"},
	])
	res := gcs_bucket.result with input as inp
	res.decision == "allow"
	mut := naming.legacy_import_mutation with input as inp
	mut.rule_id == "NAM-LEG-001"
	mut.value == "legacy"
}

# 6. Region & Environment rules
test_non_us_east1_region_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/location", "value": "US"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GLB-REG-001"
}

test_environmentsubtype_label_rejected if {
	inp := json.patch(requested_input, [{"op": "add", "path": "/document/metadata/labels/environmentsubtype", "value": "dev"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "LBL-001"
}

# 7. Secret rejection (`INV-1`)
test_secret_key_in_request_rejected if {
	inp := json.patch(requested_input, [{"op": "add", "path": "/document/spec/password", "value": "supersecret"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "INV-001"
}

# 8. Guardrail-owned field rejection at requested stage
test_guardrail_owned_field_in_requested_rejected if {
	inp := json.patch(requested_input, [{"op": "add", "path": "/document/spec/force_destroy", "value": true}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-GRD-001"
}

# 9. IAM principal & role allowlist
test_iam_user_principal_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/access/0/members/0", "value": "user:alice@example.com"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-IAM-001"
}

test_iam_storage_admin_role_rejected if {
	inp := json.patch(requested_input, [{"op": "replace", "path": "/document/spec/access/0/role", "value": "roles/storage.admin"}])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-IAM-002"
}

# 10. Lifecycle rules validation
test_lifecycle_delete_below_retention_rejected if {
	inp := json.patch(requested_input, [
		{
			"op": "replace",
			"path": "/document/spec/lifecycle_rules",
			"value": [{"action": {"type": "Delete"}, "condition": {"age_days": 30}}],
		},
	])
	res := gcs_bucket.result with input as inp
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-LFC-002"
}

test_lifecycle_valid_rule_allowed if {
	inp := json.patch(requested_input, [
		{
			"op": "replace",
			"path": "/document/spec/lifecycle_rules",
			"value": [{"action": {"type": "Delete"}, "condition": {"age_days": 120}}],
		},
	])
	res := gcs_bucket.result with input as inp
	res.decision == "allow"
}

# 11. Plan stage tests (`stage = 'plan'`, `INV-4`)
test_plan_valid_passes if {
	res := gcs_bucket.result with input as valid_plan_input
	res.decision == "allow"
	count(res.violations) == 0
}

test_plan_wrong_location_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/after/location", "value": "US"}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GLB-REG-001"
}

test_plan_pap_not_enforced_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/after/public_access_prevention", "value": "inherited"}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-PAP-001"
}

test_plan_force_destroy_true_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/after/force_destroy", "value": true}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-DEL-001"
}

test_plan_retention_locked_true_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/after/retention_policy/is_locked", "value": true}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-RET-003"
}

test_plan_missing_cmek_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/after/default_kms_key_name", "value": ""}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "GCS-ENC-001"
}

test_plan_environmentsubtype_denied if {
	bad := json.patch(valid_plan_input, [{"op": "add", "path": "/resource_changes/0/change/after/labels/environmentsubtype", "value": "dev"}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "LBL-001"
}

test_plan_unapproved_delete_action_denied if {
	bad := json.patch(valid_plan_input, [{"op": "replace", "path": "/resource_changes/0/change/actions", "value": ["delete"]}])
	res := gcs_bucket.result with input as bad
	res.decision == "deny"
	some v in res.violations
	v.rule_id == "INV-004"
}
