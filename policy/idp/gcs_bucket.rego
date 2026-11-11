package idp.gcp.gcs_bucket

import data.idp.common
import data.idp.labels
import data.idp.naming
import rego.v1

# ---------------------------------------------------------------------------
# SPP GCS Bucket Policy Package (`idp.gcp.gcs_bucket`)
# Governing ADRs & Specs:
#   - ADR-SVC-001 (First Vertical Slice — GCS Bucket End-to-End and Guardrails)
#   - ADR-GLB-006 (Naming Conventions: GCS-NAME-001..003, NAM-RSV-001, NAM-IMM-001, NAM-LEG-001)
#   - ADR-GLB-007 (Governance Gates, Guardrails, Invariants INV-1..INV-9)
#   - ADR-GLB-008 (Label Standard: 8 mandatory labels, no environmentsubtype)
#   - ADR-BP-003  (Roles, Personas, Approval Gate gcs_bucket_owner, human approval on delete)
#   - specs/examples/gcs_bucket.gates.json
# ---------------------------------------------------------------------------

stage := object.get(input, "stage", "requested")

doc := object.get(input, "document", input)

action := object.get(doc, "action", "create")

metadata := object.get(doc, "metadata", {})

spec := object.get(doc, "spec", {})

lob := object.get(metadata, "lob", "")

env := object.get(metadata, "environment", "nonprod")

data_sensitivity := object.get(metadata, "data_sensitivity", "restricted")

# Guardrail-owned fields that callers MUST NOT set at the `requested` gate (`ADR-GLB-007 GR-2`, `ADR-SVC-001 REQ-2`)
guardrail_owned_spec_fields := {
	"uniform_bucket_level_access",
	"public_access_prevention",
	"kms_key_name",
	"default_kms_key_name",
	"retention_days",
	"retention_locked",
	"soft_delete_retention_days",
	"force_destroy",
}

# Allowed Storage IAM roles on GCS buckets (`ADR-SVC-001`)
allowed_storage_roles := {
	"roles/storage.objectAdmin",
	"roles/storage.objectViewer",
	"roles/storage.objectCreator",
}

allowed_storage_classes := {
	"STANDARD",
	"NEARLINE",
	"COLDLINE",
	"ARCHIVE",
}

allowed_lifecycle_actions := {
	"Delete",
	"SetStorageClass",
}

# Default CMEK key in `us-east1` (`GCS-ENC-001` / `GCS-ENC-002`)
default_kms_key_uri := "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek"

# Resolve CMEK key URI (`GCS-ENC-001` / `GCS-ENC-002`): must be in `locations/us-east1`
resolved_kms_key := kms if {
	override := object.get(input, "kms_key_name", "")
	override != ""
	kms := override
} else := default_kms_key_uri

# ---------------------------------------------------------------------------
# Stage 1 & 2 (`requested` and `approved`) Violations
# ---------------------------------------------------------------------------

# Inherit common & naming & label violations for requested/approved stages
request_violations contains v if {
	stage in {"requested", "approved"}
	some v in common.violations
}

request_violations contains v if {
	stage in {"requested", "approved"}
	some v in naming.violations
}

request_violations contains v if {
	stage in {"requested", "approved"}
	some v in labels.violations
}

# Reject guardrail-owned fields when supplied by user at `requested` stage (`ADR-GLB-007 GR-2`)
request_violations contains v if {
	stage == "requested"
	some field in guardrail_owned_spec_fields
	field in object.keys(spec)
	v := {
		"rule_id": "GCS-GRD-001",
		"path": sprintf("/spec/%s", [field]),
		"message": sprintf("field '/spec/%s' is guardrail-owned and cannot be set in a requested document (ADR-GLB-007 GR-2)", [field]),
	}
}

# Location must be `us-east1` (`ADR-SVC-001 GR-1`)
request_violations contains v if {
	stage in {"requested", "approved"}
	loc := object.get(spec, "location", "")
	loc != "us-east1"
	v := {
		"rule_id": "GLB-REG-001",
		"path": "/spec/location",
		"message": sprintf("gcs_bucket location must be 'us-east1' in all environments (got '%v')", [loc]),
	}
}

# Storage class validation
request_violations contains v if {
	stage in {"requested", "approved"}
	sc := object.get(spec, "storage_class", "STANDARD")
	not sc in allowed_storage_classes
	v := {
		"rule_id": "GCS-CLS-001",
		"path": "/spec/storage_class",
		"message": sprintf("storage_class '%v' is not in allowed set %v", [sc, allowed_storage_classes]),
	}
}

# IAM principal restriction: only `group:` and `serviceAccount:` allowed (`ADR-BP-003`, `ADR-SVC-001`)
request_violations contains v if {
	stage in {"requested", "approved"}
	access_list := object.get(spec, "access", [])
	some i, entry in access_list
	members := object.get(entry, "members", [])
	some m in members
	not startswith(m, "group:")
	not startswith(m, "serviceAccount:")
	v := {
		"rule_id": "GCS-IAM-001",
		"path": sprintf("/spec/access/%d/members", [i]),
		"message": sprintf("IAM member '%s' is forbidden; only 'group:' and 'serviceAccount:' principals are allowed (no 'user:', 'allUsers', or 'allAuthenticatedUsers')", [m]),
	}
}

# IAM role allowlist restriction (`ADR-SVC-001`)
request_violations contains v if {
	stage in {"requested", "approved"}
	access_list := object.get(spec, "access", [])
	some i, entry in access_list
	role := object.get(entry, "role", "")
	not role in allowed_storage_roles
	v := {
		"rule_id": "GCS-IAM-002",
		"path": sprintf("/spec/access/%d/role", [i]),
		"message": sprintf("IAM role '%s' is not in the GCS bucket role allowlist %v", [role, allowed_storage_roles]),
	}
}

# Versioning + retention mutual exclusion in GCS (`GCS-RET-001`, `ADR-SVC-001 REQ-2`)
request_violations contains v if {
	stage in {"requested", "approved"}
	object.get(spec, "versioning", false) == true
	object.get(spec, "retention_days", 90) > 0
	object.get(spec, "allow_versioning_without_retention", false) != true
	v := {
		"rule_id": "GCS-RET-001",
		"path": "/spec/versioning",
		"message": "GCS-RET-001: bucket retention policy (90 days) cannot be combined with versioning=true",
	}
}

# Optional user-configurable lifecycle_rules validation (default is `[]` / NONE, `ADR-SVC-001 REQ-3`)
request_violations contains v if {
	stage in {"requested", "approved"}
	rules := object.get(spec, "lifecycle_rules", [])
	not is_array(rules)
	v := {
		"rule_id": "GCS-LFC-001",
		"path": "/spec/lifecycle_rules",
		"message": "spec.lifecycle_rules must be an array (default [])",
	}
}

request_violations contains v if {
	stage in {"requested", "approved"}
	rules := object.get(spec, "lifecycle_rules", [])
	is_array(rules)
	some i, r in rules
	act_type := object.get(object.get(r, "action", {}), "type", "")
	not act_type in allowed_lifecycle_actions
	v := {
		"rule_id": "GCS-LFC-001",
		"path": sprintf("/spec/lifecycle_rules/%d/action/type", [i]),
		"message": sprintf("lifecycle_rules action.type '%v' must be one of %v", [act_type, allowed_lifecycle_actions]),
	}
}

request_violations contains v if {
	stage in {"requested", "approved"}
	rules := object.get(spec, "lifecycle_rules", [])
	is_array(rules)
	some i, r in rules
	act_type := object.get(object.get(r, "action", {}), "type", "")
	act_type == "Delete"
	cond := object.get(r, "condition", {})
	age := object.get(cond, "age_days", object.get(cond, "age", 0))
	age > 0
	ret_days := object.get(spec, "retention_days", 90)
	age < ret_days
	v := {
		"rule_id": "GCS-LFC-002",
		"path": sprintf("/spec/lifecycle_rules/%d/condition/age_days", [i]),
		"message": sprintf("Delete lifecycle rule age_days (%d) must be >= retention_days (%d)", [age, ret_days]),
	}
}

# Approved stage verification when an already-enriched approved document is validated
request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	object.get(spec, "uniform_bucket_level_access", null) != true
	v := {
		"rule_id": "GCS-UBLA-001",
		"path": "/spec/uniform_bucket_level_access",
		"message": "GCS-UBLA-001: approved spec must have uniform_bucket_level_access == true",
	}
}

request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	object.get(spec, "public_access_prevention", "") != "enforced"
	v := {
		"rule_id": "GCS-PAP-001",
		"path": "/spec/public_access_prevention",
		"message": "GCS-PAP-001: approved spec must have public_access_prevention == 'enforced'",
	}
}

request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	kms := object.get(spec, "kms_key_name", "")
	not contains(kms, "/locations/us-east1/")
	v := {
		"rule_id": "GCS-ENC-001",
		"path": "/spec/kms_key_name",
		"message": sprintf("GCS-ENC-001: approved spec kms_key_name '%s' must be in locations/us-east1", [kms]),
	}
}

request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	object.get(spec, "retention_locked", null) != false
	v := {
		"rule_id": "GCS-RET-003",
		"path": "/spec/retention_locked",
		"message": "GCS-RET-003: retention_locked must be false by default",
	}
}

request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	object.get(spec, "force_destroy", null) != false
	v := {
		"rule_id": "GCS-DEL-001",
		"path": "/spec/force_destroy",
		"message": "GCS-DEL-001: force_destroy must be false",
	}
}

request_violations contains v if {
	stage == "approved"
	object.get(input, "verify_enriched", false) == true
	some v in labels.validate_labels_map(object.get(metadata, "labels", {}), "/metadata/labels")
}

# ---------------------------------------------------------------------------
# Stage 2 (`approved`) Guardrail Trace & Mutations (`specs/examples/gcs_bucket.gates.json`)
# ---------------------------------------------------------------------------

ad_groups := [m |
	some entry in object.get(spec, "access", [])
	some m in object.get(entry, "members", [])
	startswith(m, "group:")
]

first_ad_group := ad_groups[0] if {
	count(ad_groups) > 0
} else := sprintf("group:gcp-%s-%s-orders-read@example.com", [lob, env])

vpc_sc_perimeter := sprintf("%s_%s_restricted_perimeter", [lob, env])

base_guardrail_trace := [
	{
		"rule_id": "GCS-UBLA-001",
		"path": "/spec/uniform_bucket_level_access",
		"from": object.get(spec, "uniform_bucket_level_access", null),
		"to": true,
		"reason": "Uniform bucket-level access is mandatory. Legacy form value 'false' was not carried [truncated in source]",
	},
	{
		"rule_id": "GCS-PAP-001",
		"path": "/spec/public_access_prevention",
		"from": object.get(spec, "public_access_prevention", null),
		"to": "enforced",
		"reason": "Unverified (source gap): lines 332-335 [NOT CAPTURED] in photo; value 'enforced' confirmed from approved.document.spec.public_access_prevention.",
	},
	{
		"rule_id": "GCS-ENC-001",
		"path": "/spec/kms_key_name",
		"from": object.get(spec, "kms_key_name", null),
		"to": resolved_kms_key,
		"reason": sprintf("CMEK resolved by (lob=%s, environment_type=%s, location=us-east1); key location 'us-east1' matches bucket [truncated in source; overridden from US to us-east1]", [lob, env]),
	},
	{
		"rule_id": "GCS-RET-001",
		"path": "/spec/retention_days",
		"from": object.get(spec, "retention_days", null),
		"to": 90,
		"reason": "Retention floor for restricted data (illustrative value; set by the GCS ADR). Versioning stays off [truncated in source]",
	},
	{
		"rule_id": "GCS-RET-003",
		"path": "/spec/retention_locked",
		"from": object.get(spec, "retention_locked", null),
		"to": false,
		"reason": "Locks are irreversible and only applied on an explicit records-management request.",
	},
	{
		"rule_id": "GCS-SDP-001",
		"path": "/spec/soft_delete_retention_days",
		"from": object.get(spec, "soft_delete_retention_days", null),
		"to": 7,
		"reason": "Soft-delete window for accidental deletes.",
	},
	{
		"rule_id": "GCS-DEL-001",
		"path": "/spec/force_destroy",
		"from": object.get(spec, "force_destroy", null),
		"to": false,
		"reason": "The platform never force-destroys a bucket with objects in it.",
	},
	{
		"rule_id": "LBL-001",
		"path": "/metadata/labels",
		"from": object.get(metadata, "labels", {}),
		"to": labels.computed_labels,
		"reason": "Mandatory labels merged with user labels; one key set for every kind.",
	},
	{
		"rule_id": "PRQ-001",
		"path": "/prerequisites/0",
		"from": null,
		"to": "ad_group",
		"reason": "The read group must exist before the IAM binding [truncated in source]",
	},
]

prq_002_trace := [
	{
		"rule_id": "PRQ-002",
		"path": "/prerequisites/1",
		"from": null,
		"to": "vpc_sc_ingress",
		"reason": "Unverified (source gap): lines 384-428 [NOT CAPTURED] in photo; prerequisite vpc_sc_ingress with params.perimeter confirmed from approved.document.prerequisites.",
	},
] if {
	data_sensitivity == "restricted"
} else := []

guardrail_trace := array.concat(base_guardrail_trace, prq_002_trace) if {
	stage == "approved"
} else := []

mutations := [
	{
		"rule_id": entry.rule_id,
		"op": "set",
		"path": entry.path,
		"value": entry.to,
		"reason": entry.reason,
	} |
	some entry in guardrail_trace
]

prerequisites := array.concat(
	[
		{
			"type": "ad_group",
			"target": first_ad_group,
			"rule_id": "PRQ-001",
		},
	],
	[p |
		data_sensitivity == "restricted"
		p := {
			"type": "vpc_sc_ingress",
			"target": first_ad_group,
			"params": {"perimeter": vpc_sc_perimeter},
			"rule_id": "PRQ-002",
		}
	],
)

# ---------------------------------------------------------------------------
# Stage 3 (`plan`) Terraform `plan.json` Evaluation (`INV-4`, Conftest compatible)
# ---------------------------------------------------------------------------

is_plan_input if {
	stage == "plan"
} else if {
	"resource_changes" in object.keys(input)
}

bucket_changes := [rc |
	is_plan_input
	some rc in object.get(input, "resource_changes", [])
	object.get(rc, "type", "") == "google_storage_bucket"
]

plan_violations contains v if {
	is_plan_input
	some v in common.secret_violations
}

# Check for unapproved delete / replace actions in resource_changes (`destroy_without_delete_request`)
plan_violations contains v if {
	is_plan_input
	some rc in object.get(input, "resource_changes", [])
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	"delete" in actions
	object.get(input, "approved_delete_request", false) != true
	v := {
		"rule_id": "INV-004",
		"path": sprintf("/resource_changes/%s/change/actions", [object.get(rc, "address", "unknown")]),
		"message": "destroy_without_delete_request: Terraform plan contains a delete/replace action without an explicit human-approved delete request",
	}
}

# Validate bucket attributes in plan.json `change.after`
plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	loc := lower(object.get(after, "location", ""))
	loc != "us-east1"
	v := {
		"rule_id": "GLB-REG-001",
		"path": "/location",
		"message": sprintf("GLB-REG-001: bucket location in plan must be 'us-east1' (got '%v')", [object.get(after, "location", "")]),
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	object.get(after, "public_access_prevention", "") != "enforced"
	v := {
		"rule_id": "GCS-PAP-001",
		"path": "/public_access_prevention",
		"message": "GCS-PAP-001: bucket public_access_prevention in plan must be 'enforced'",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	ubla := object.get(after, "uniform_bucket_level_access", false)
	ubla != true
	v := {
		"rule_id": "GCS-UBLA-001",
		"path": "/uniform_bucket_level_access",
		"message": "GCS-UBLA-001: bucket uniform_bucket_level_access in plan must be true",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	object.get(after, "force_destroy", true) != false
	v := {
		"rule_id": "GCS-DEL-001",
		"path": "/force_destroy",
		"message": "GCS-DEL-001: bucket force_destroy in plan must be false",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	kms := extract_plan_kms(after)
	not valid_plan_kms(kms)
	v := {
		"rule_id": "GCS-ENC-001",
		"path": "/default_kms_key_name",
		"message": sprintf("GCS-ENC-001: bucket CMEK key '%v' must be non-empty and in locations/us-east1", [kms]),
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	ret := extract_plan_retention(after)
	object.get(ret, "retention_period", 0) < 7776000
	v := {
		"rule_id": "GCS-RET-001",
		"path": "/retention_policy/retention_period",
		"message": "GCS-RET-001: bucket retention_period in plan must be >= 7776000 seconds (90 days)",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	ret := extract_plan_retention(after)
	object.get(ret, "is_locked", false) != false
	v := {
		"rule_id": "GCS-RET-003",
		"path": "/retention_policy/is_locked",
		"message": "GCS-RET-003: bucket retention_policy.is_locked in plan must be false",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	sdp := extract_plan_soft_delete(after)
	object.get(sdp, "retention_duration_seconds", 0) != 604800
	v := {
		"rule_id": "GCS-SDP-001",
		"path": "/soft_delete_policy/retention_duration_seconds",
		"message": "GCS-SDP-001: bucket soft_delete_policy.retention_duration_seconds in plan must be 604800 (7 days)",
	}
}

plan_violations contains v if {
	some rc in bucket_changes
	actions := object.get(object.get(rc, "change", {}), "actions", [])
	not "delete" in actions
	after := object.get(object.get(rc, "change", {}), "after", {})
	lbls := object.get(after, "labels", {})
	some v in labels.validate_labels_map(lbls, "/labels")
}

extract_plan_kms(after) := kms if {
	kms := object.get(after, "default_kms_key_name", "")
	kms != ""
} else := kms if {
	enc := object.get(after, "encryption", [])
	is_array(enc)
	count(enc) > 0
	kms := object.get(enc[0], "default_kms_key_name", "")
} else := ""

valid_plan_kms(kms) if {
	is_string(kms)
	kms != ""
	contains(kms, "/locations/us-east1/")
}

extract_plan_retention(after) := ret if {
	rp := object.get(after, "retention_policy", {})
	is_object(rp)
	ret := rp
} else := ret if {
	rp := object.get(after, "retention_policy", [])
	is_array(rp)
	count(rp) > 0
	ret := rp[0]
} else := {}

extract_plan_soft_delete(after) := sdp if {
	sp := object.get(after, "soft_delete_policy", {})
	is_object(sp)
	sdp := sp
} else := sdp if {
	sp := object.get(after, "soft_delete_policy", [])
	is_array(sp)
	count(sp) > 0
	sdp := sp[0]
} else := {}

# ---------------------------------------------------------------------------
# Unified Decision Output (`allow`, `deny`, `allow_with_mutations`) & Conftest `deny`
# ---------------------------------------------------------------------------

violations := plan_violations if {
	is_plan_input
} else := request_violations

deny contains msg if {
	some v in violations
	msg := sprintf("[%s] %s (%s)", [v.rule_id, v.message, v.path])
}

decision := "deny" if {
	count(violations) > 0
} else := "allow_with_mutations" if {
	stage == "approved"
	count(mutations) > 0
} else := "allow"

result := {
	"decision": decision,
	"violations": [v | some v in violations],
	"mutations": mutations,
	"guardrail_trace": guardrail_trace,
	"computed_labels": labels.computed_labels,
	"prerequisites": prerequisites,
	"resolved_kms_key": resolved_kms_key,
}
