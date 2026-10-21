package idp.common

import rego.v1

# ---------------------------------------------------------------------------
# SPP Common Invariants (`ADR-GLB-001`, `ADR-GLB-007`, `INV-1`, `INV-4`)
# - Zero secret keys or secret-like values in any gate payload (`INV-1`)
# - Cloud must be `gcp`, region must be `us-east1` (`ADR-GLB-001`, `ADR-GLB-007`)
# - Environment must be `nonprod` or `prod` (`ADR-GLB-006`, `ADR-GLB-008`)
# - No unapproved delete/destroy/replace in any environment (`ADR-GLB-007`, `ADR-BP-003`)
# ---------------------------------------------------------------------------

forbidden_secret_keys := {
	"password",
	"passwd",
	"client_secret",
	"private_key",
	"secret_value",
	"api_key",
	"token",
}

forbidden_secret_value_patterns := [
	`-----BEGIN [A-Z ]*PRIVATE KEY-----`,
	`(?i)^(ghp|gho|github_pat)_[A-Za-z0-9_]+$`,
	`(?i)^AKIA[0-9A-Z]{16}$`,
	`(?i)^AIza[0-9A-Za-z\-_]{35}$`,
]

allowed_environments := {"nonprod", "prod"}

# INV-1: Secret key detection across document tree
secret_violations contains v if {
	some path, val
	walk(input, [path, val])
	val != null
	count(path) > 0
	key := lower(sprintf("%v", [path[count(path) - 1]]))
	key in forbidden_secret_keys
	v := {
		"rule_id": "INV-001",
		"path": sprintf("/%s", [concat("/", [sprintf("%v", [p]) | some p in path])]),
		"message": sprintf("INV-1 violation: forbidden secret key '%s' is not permitted in control-plane documents", [key]),
	}
}

# INV-1: Secret value detection across document tree
secret_violations contains v if {
	some path, val
	walk(input, [path, val])
	is_string(val)
	some pattern in forbidden_secret_value_patterns
	regex.match(pattern, val)
	v := {
		"rule_id": "INV-001",
		"path": sprintf("/%s", [concat("/", [sprintf("%v", [p]) | some p in path])]),
		"message": "INV-1 violation: secret-like value detected in document",
	}
}

# Cloud & Region check (`ADR-GLB-001`, `ADR-GLB-007`)
region_violations contains v if {
	cloud := object.get(input, "cloud", "gcp")
	cloud != "gcp"
	v := {
		"rule_id": "GLB-CLD-001",
		"path": "/cloud",
		"message": sprintf("only cloud 'gcp' is supported (got '%v')", [cloud]),
	}
}

region_violations contains v if {
	doc := object.get(input, "document", input)
	spec := object.get(doc, "spec", {})
	loc := object.get(spec, "location", "us-east1")
	loc != "us-east1"
	v := {
		"rule_id": "GLB-REG-001",
		"path": "/spec/location",
		"message": sprintf("only region 'us-east1' is allowed in nonprod and prod (got '%v')", [loc]),
	}
}

# Environment check (`ADR-GLB-006`, `ADR-GLB-008`)
environment_violations contains v if {
	doc := object.get(input, "document", input)
	meta := object.get(doc, "metadata", {})
	env := object.get(meta, "environment", "")
	env != ""
	not env in allowed_environments
	v := {
		"rule_id": "GLB-ENV-001",
		"path": "/metadata/environment",
		"message": sprintf("metadata.environment must be 'nonprod' or 'prod' (got '%v')", [env]),
	}
}

# Never auto-approve delete (`ADR-GLB-007`, `ADR-BP-003`)
delete_approval_violations contains v if {
	doc := object.get(input, "document", input)
	action := object.get(doc, "action", "create")
	action == "delete"
	approval_status := upper(object.get(input, "approval_status", ""))
	approval_status == "AUTO_APPROVED"
	v := {
		"rule_id": "GLB-DEL-001",
		"path": "/action",
		"message": "delete requests require explicit human approval in all environments; AUTO_APPROVED is forbidden",
	}
}

violations := ((secret_violations | region_violations) | environment_violations) | delete_approval_violations
