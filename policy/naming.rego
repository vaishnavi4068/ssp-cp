package idp.naming

import rego.v1

# ---------------------------------------------------------------------------
# SPP Naming Policy (`ADR-GLB-006`, `specs/naming/naming-spec.json`)
# Enforces:
#   - GCS-NAME-001: `{lob}-{env}-{app}-{purpose}-{suffix}` (`max 63`, `env` in `nonprod` | `prod`, no hyphen)
#   - GCS-NAME-002: no `goog` prefix and no `google` or `g00gle` substring
#   - NAM-RSV-001: purpose token is not a reserved word
#   - NAM-IMM-001: update action keeps the exact name of the existing resource
#   - NAM-LEG-001: import action allows existing name and injects label `idp_naming = "legacy"`
#   - SPN-NAME-001..002: Spanner instance and database naming rules
# ---------------------------------------------------------------------------

reserved_purpose_words := {
	"non-prod",
	"nonprod",
	"prod",
	"sandbox",
	"dev",
	"qa",
	"test",
	"pdev",
	"pqa",
	"preprod",
	"restricted",
	"unrestricted",
}

forbidden_gcs_prefixes := ["goog"]

forbidden_gcs_substrings := ["google", "g00gle"]

doc := object.get(input, "document", input)

kind := object.get(doc, "kind", "gcs_bucket")

action := object.get(doc, "action", "create")

metadata := object.get(doc, "metadata", {})

spec := object.get(doc, "spec", {})

name := object.get(spec, "name", "")

lob := object.get(metadata, "lob", "")

env := object.get(metadata, "environment", "")

app := object.get(input, "app_alias", object.get(object.get(metadata, "labels", {}), "app", "orders"))

existing_name := object.get(input, "existing_name", "")

# Helper: extract purpose token from a bucket name `{lob}-{env}-{app}-{purpose}-{suffix}`
bucket_prefix := sprintf("%s-%s-%s-", [lob, env, app])

has_valid_bucket_prefix if {
	startswith(name, bucket_prefix)
	count(name) > count(bucket_prefix) + 5
}

extracted_suffix := substring(name, count(name) - 4, 4) if {
	count(name) >= 5
	substring(name, count(name) - 5, 1) == "-"
}

extracted_purpose := substring(name, count(bucket_prefix), count(name) - count(bucket_prefix) - 5) if {
	has_valid_bucket_prefix
	extracted_suffix
}

valid_kebab_purpose(p) if {
	count(p) >= 2
	count(p) <= 20
	regex.match(`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, p)
}

valid_suffix(s) if {
	regex.match(`^[a-z0-9]{4}$`, s)
}

valid_lob(l) if {
	l == "<lob>"
} else if {
	regex.match(`^[a-z][a-z0-9]{1,5}$`, l)
}

# App ID (`apm_id`) format check: `^APM\d{5}$` case-insensitive (`apm12345` normalized)
violations contains v if {
	apm_id := object.get(metadata, "apm_id", "")
	not regex.match(`^(?i)apm[0-9]{5}$`, apm_id)
	v := {
		"rule_id": "NAM-APM-001",
		"path": "/metadata/apm_id",
		"message": sprintf("NAM-APM-001: metadata.apm_id '%v' must match ^APM\\d{5}$ (case-insensitive, normalized to lowercase apm\\d{5})", [apm_id]),
	}
}

# GCS-NAME-002: Forbidden 'goog' prefix or 'google' / 'g00gle' substring
violations contains v if {
	kind == "gcs_bucket"
	action != "import"
	lower_name := lower(name)
	some p in forbidden_gcs_prefixes
	startswith(lower_name, p)
	v := {
		"rule_id": "GCS-NAME-002",
		"path": "/spec/name",
		"message": sprintf("GCS-NAME-002: bucket name '%s' must not start with forbidden prefix '%s'", [name, p]),
	}
}

violations contains v if {
	kind == "gcs_bucket"
	action != "import"
	lower_name := lower(name)
	some sub in forbidden_gcs_substrings
	contains(lower_name, sub)
	v := {
		"rule_id": "GCS-NAME-002",
		"path": "/spec/name",
		"message": sprintf("GCS-NAME-002: bucket name '%s' must not contain forbidden substring '%s'", [name, sub]),
	}
}

# NAM-RSV-001: Purpose is a reserved word
violations contains v if {
	kind == "gcs_bucket"
	action != "import"
	extracted_purpose in reserved_purpose_words
	v := {
		"rule_id": "NAM-RSV-001",
		"path": "/spec/name",
		"message": sprintf("NAM-RSV-001: purpose token '%s' in '%s' is a reserved word", [extracted_purpose, name]),
	}
}

# NAM-IMM-001: Update cannot rename an existing resource
violations contains v if {
	action == "update"
	existing_name != ""
	name != existing_name
	v := {
		"rule_id": "NAM-IMM-001",
		"path": "/spec/name",
		"message": sprintf("NAM-IMM-001: update request cannot rename resource from '%s' to '%s'", [existing_name, name]),
	}
}

# GCS-NAME-001: Bucket name must match `{lob}-{env}-{app}-{purpose}-{suffix}` (max 63 chars, lowercase)
valid_gcs_bucket_name if {
	count(name) <= 63
	name == lower(name)
	env in {"nonprod", "prod"}
	valid_lob(lob)
	has_valid_bucket_prefix
	valid_suffix(extracted_suffix)
	valid_kebab_purpose(extracted_purpose)
}

violations contains v if {
	kind == "gcs_bucket"
	action in {"create", "update"}
	not valid_gcs_bucket_name
	v := {
		"rule_id": "GCS-NAME-001",
		"path": "/spec/name",
		"message": sprintf("GCS-NAME-001: bucket name '%s' does not match template '{lob}-{env}-{app}-{purpose}-{suffix}' for lob='%s', env='%s', app='%s'", [name, lob, env, app]),
	}
}

# SPN-NAME-001: Spanner instance `{lob}-{env}-{app}[-{purpose}]`
spn_base := sprintf("%s-%s-%s", [lob, env, app])

valid_spanner_instance_name if {
	count(name) <= 64
	name == lower(name)
	env in {"nonprod", "prod"}
	valid_lob(lob)
	name == spn_base
} else if {
	count(name) <= 64
	name == lower(name)
	env in {"nonprod", "prod"}
	valid_lob(lob)
	startswith(name, sprintf("%s-", [spn_base]))
	p := substring(name, count(spn_base) + 1, count(name) - count(spn_base) - 1)
	valid_kebab_purpose(p)
	not p in reserved_purpose_words
}

violations contains v if {
	kind == "spanner_instance"
	action in {"create", "update"}
	not valid_spanner_instance_name
	v := {
		"rule_id": "SPN-NAME-001",
		"path": "/spec/name",
		"message": sprintf("SPN-NAME-001: spanner instance name '%s' does not match '{lob}-{env}-{app}[-{purpose}]'", [name]),
	}
}

# SPN-NAME-002: Spanner database `{app}[_{purpose}]`
valid_spanner_database_name if {
	count(name) <= 30
	name == app
} else if {
	count(name) <= 30
	startswith(name, sprintf("%s_", [app]))
	p := substring(name, count(app) + 1, count(name) - count(app) - 1)
	count(p) >= 2
	count(p) <= 17
	regex.match(`^[a-z][a-z0-9]*(_[a-z0-9]+)*$`, p)
	not p in reserved_purpose_words
}

violations contains v if {
	kind == "spanner_database"
	action in {"create", "update"}
	not valid_spanner_database_name
	v := {
		"rule_id": "SPN-NAME-002",
		"path": "/spec/name",
		"message": sprintf("SPN-NAME-002: spanner database name '%s' does not match '{app}' or '{app}_{purpose}'", [name]),
	}
}

# NAM-LEG-001: Import legacy naming marker
legacy_import_mutation := {
	"rule_id": "NAM-LEG-001",
	"op": "add",
	"path": "/metadata/labels/idp_naming",
	"value": "legacy",
	"reason": "Import preserves existing resource name and marks idp_naming=legacy.",
} if {
	action == "import"
	kind == "gcs_bucket"
	not valid_gcs_bucket_name
}
