package idp.labels

import rego.v1

# ---------------------------------------------------------------------------
# SPP Label Standard (`ADR-GLB-008`, `LBL-001`, `LBL-002`)
# - 8 Mandatory labels:
#     1. `sppappid`
#     2. `costcenter`
#     3. `environmenttype` (`nonprod` | `prod` ONLY)
#     4. `primarylob`
#     5. `datasensitivity`
#     6. `owner`
#     7. `provisionedby` (`idp`)
#     8. `idp_resource_id`
# - `environmentsubtype` is DROPPED and FORBIDDEN everywhere.
# - Metadata-derived labels: `dataclassification`, `sharedemailaddress`, `tenancy`
# - Value normalization (`LBL-002`): lowercase, replace `[^a-z0-9_-]` with `_`, max 63 chars, drop empty
# ---------------------------------------------------------------------------

mandatory_label_keys := [
	"sppappid",
	"costcenter",
	"environmenttype",
	"primarylob",
	"datasensitivity",
	"owner",
	"provisionedby",
	"idp_resource_id",
]

allowed_environment_types := {"nonprod", "prod"}

doc := object.get(input, "document", input)

metadata := object.get(doc, "metadata", {})

user_labels := object.get(metadata, "labels", {})

resource_id := object.get(input, "resource_id", object.get(user_labels, "idp_resource_id", ""))

# Normalize a label value per LBL-002 (`<lob>` token placeholder preserved for spec fixtures)
normalize_label_value(raw) := out if {
	is_string(raw)
	lower_val := lower(raw)
	replaced := replace(lower_val, "<lob>", "__lob_placeholder__")
	cleaned := regex.replace(replaced, `[^a-z0-9_-]`, "_")
	restored := replace(cleaned, "__lob_placeholder__", "<lob>")
	out := substring(restored, 0, min([count(restored), 63]))
}

# Compute canonical label map (LBL-001 + LBL-002)
normalized_user_labels[k] := v if {
	some k, raw_v in user_labels
	k != "environmentsubtype"
	v := normalize_label_value(sprintf("%v", [raw_v]))
	v != ""
}

derived_labels := object.union(
	normalized_user_labels,
	{
		"costcenter": normalize_label_value(object.get(metadata, "cost_center", "")),
		"dataclassification": normalize_label_value(object.get(metadata, "data_classification", "")),
		"datasensitivity": normalize_label_value(object.get(metadata, "data_sensitivity", "")),
		"environmenttype": normalize_label_value(object.get(metadata, "environment", "")),
		"idp_resource_id": normalize_label_value(resource_id),
		"owner": normalize_label_value(object.get(metadata, "owner", "")),
		"primarylob": normalize_label_value(object.get(metadata, "lob", "")),
		"provisionedby": "idp",
		"sharedemailaddress": normalize_label_value(object.get(metadata, "shared_mailbox", "")),
		"sppappid": normalize_label_value(object.get(metadata, "apm_id", "")),
		"tenancy": normalize_label_value(object.get(metadata, "tenancy", "")),
	},
)

computed_labels[k] := v if {
	some k, v in derived_labels
	v != ""
}

# Violations on labels at requested/approved/plan gates
violations contains v if {
	"environmentsubtype" in object.keys(user_labels)
	v := {
		"rule_id": "LBL-001",
		"path": "/metadata/labels/environmentsubtype",
		"message": "LBL-001: 'environmentsubtype' label is dropped and forbidden everywhere; use 'environmenttype' ('nonprod' | 'prod')",
	}
}

violations contains v if {
	env_type := object.get(computed_labels, "environmenttype", "")
	env_type != ""
	not env_type in allowed_environment_types
	v := {
		"rule_id": "LBL-001",
		"path": "/metadata/labels/environmenttype",
		"message": sprintf("LBL-001: 'environmenttype' must be 'nonprod' or 'prod' (got '%s')", [env_type]),
	}
}

violations contains v if {
	app_id := object.get(computed_labels, "sppappid", "")
	app_id != ""
	not regex.match(`^apm[0-9]{5}$`, app_id)
	v := {
		"rule_id": "LBL-001",
		"path": "/metadata/labels/sppappid",
		"message": sprintf("LBL-001: 'sppappid' must match normalized ^apm\\d{5}$ (e.g. 'apm12345', got '%s')", [app_id]),
	}
}

# Validate an already-materialized label map (e.g. in Approved doc or Terraform plan)
validate_labels_map(labels_obj, base_path) := vs if {
	v1 := [v |
		"environmentsubtype" in object.keys(labels_obj)
		v := {
			"rule_id": "LBL-001",
			"path": sprintf("%s/environmentsubtype", [base_path]),
			"message": "LBL-001: 'environmentsubtype' label is forbidden; only 8 mandatory labels with 'environmenttype' in {'nonprod', 'prod'} are allowed",
		}
	]
	v2 := [v |
		some req_key in mandatory_label_keys
		val := object.get(labels_obj, req_key, "")
		trim_space(sprintf("%v", [val])) == ""
		v := {
			"rule_id": "LBL-001",
			"path": sprintf("%s/%s", [base_path, req_key]),
			"message": sprintf("LBL-001: missing or empty mandatory label '%s'", [req_key]),
		}
	]
	v3 := [v |
		env_val := object.get(labels_obj, "environmenttype", "")
		env_val != ""
		not env_val in allowed_environment_types
		v := {
			"rule_id": "LBL-001",
			"path": sprintf("%s/environmenttype", [base_path]),
			"message": sprintf("LBL-001: label 'environmenttype' must be 'nonprod' or 'prod' (got '%v')", [env_val]),
		}
	]
	v4 := [v |
		app_val := object.get(labels_obj, "sppappid", "")
		app_val != ""
		not regex.match(`^apm[0-9]{5}$`, app_val)
		v := {
			"rule_id": "LBL-001",
			"path": sprintf("%s/sppappid", [base_path]),
			"message": sprintf("LBL-001: label 'sppappid' must match lowercase ^apm\\d{5}$ (e.g. 'apm12345', got '%v')", [app_val]),
		}
	]
	vs := array.concat(array.concat(v1, v2), array.concat(v3, v4))
}
