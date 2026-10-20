-- Migration 0001 from ssp-doc/10-product/11-domain-model.md (goose).
-- Schema only. TransitionOrder (SSP-DM-001) and monthly partitioning (SSP-DM-006) are T-0002.

-- +goose Up
create schema ssp;

create type ssp.cloud as enum ('gcp', 'aws', 'azure');
create type ssp.tenant_kind as enum ('project', 'account', 'subscription');
create type ssp.order_kind as enum ('create', 'change', 'decommission', 'upgrade', 'adopt', 'import');
create type ssp.order_state as enum ('requested', 'approved', 'expected', 'observed', 'rejected', 'cancelled', 'failed');
create type ssp.approval_gate as enum ('none', 'cr_pending', 'owner_signoff_pending');
create type ssp.run_kind as enum ('plan', 'apply', 'refresh', 'import', 'destroy');
create type ssp.run_state as enum ('queued', 'running', 'succeeded', 'failed', 'cancelled');
create type ssp.drift_class as enum ('benign', 'config', 'missing', 'unmanaged');

create table ssp.lob (
  lob_id        text primary key,
  name          text not null,
  cloud         ssp.cloud not null,
  boundary_ref  text not null,
  state_bucket  text not null,
  cmek_key      text not null,
  created_at    timestamptz not null default now()
);

create table ssp.tenant (
  tenant_id         text primary key,
  lob_id            text not null references ssp.lob,
  cloud             ssp.cloud not null,
  kind              ssp.tenant_kind not null,
  boundary_ref      text not null,
  apm_id            text not null,
  tier              smallint not null check (tier between 1 and 4),
  data_class        text not null,
  cost_center       text not null,
  env               text not null,
  tenant_sa         text not null,
  state_prefix      text not null,
  paused            boolean not null default false,
  break_glass_until timestamptz,
  created_at        timestamptz not null default now(),
  unique (cloud, boundary_ref)
);

create table ssp.principal (
  principal_id text primary key,
  email        text not null unique,
  display_name text,
  personas     text[] not null default '{buyer}'
);

create table ssp.entitlement (
  principal_id text references ssp.principal,
  apm_id       text not null,
  role         text not null check (role in ('buyer', 'app_owner')),
  primary key (principal_id, apm_id)
);

create table ssp.catalog_service (
  service_id    text primary key,
  cloud         ssp.cloud not null,
  display_name  text not null,
  category      text not null,
  adr_id        text not null,
  owner_mailbox text not null,
  enabled       boolean not null default true
);

create table ssp.service_version (
  service_id     text references ssp.catalog_service,
  version        text not null,
  bundle_uri     text not null,
  module_source  text not null,
  spec           jsonb not null,
  request_schema jsonb not null,
  ui_template    jsonb not null,
  pricing        jsonb not null,
  policy_digest  text not null,
  published_at   timestamptz not null default now(),
  deprecated     boolean not null default false,
  primary key (service_id, version)
);

create table ssp."order" (
  order_id             text primary key,
  idempotency_key      text not null unique,
  kind                 ssp.order_kind not null,
  state                ssp.order_state not null default 'requested',
  gate                 ssp.approval_gate not null default 'none',
  tenant_id            text not null references ssp.tenant,
  service_id           text not null,
  service_version      text not null,
  resource_instance_id text,
  requested_by         text not null references ssp.principal,
  requested_params     jsonb not null,
  preview_hash         text not null,
  channel              text not null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  foreign key (service_id, service_version) references ssp.service_version
);
create index order_tenant_state_idx on ssp."order" (tenant_id, state);
create index order_requested_by_created_idx on ssp."order" (requested_by, created_at desc);

create table ssp.approved_spec (
  order_id         text primary key references ssp."order",
  approved_params  jsonb not null,
  guardrails       jsonb not null,
  policy_decision  jsonb not null,
  estimate         jsonb not null,
  cr_id            text,
  owner_signoff_by text references ssp.principal,
  approved_by      text not null,
  spec_hash        text not null,
  approved_at      timestamptz not null default now()
);

create table ssp.resource_instance (
  resource_instance_id text primary key,
  tenant_id            text not null references ssp.tenant,
  service_id           text not null,
  service_version      text not null,
  name                 text not null,
  params               jsonb not null,
  state                text not null default 'expected',
  outputs              jsonb,
  last_observed_at     timestamptz,
  created_by_order     text references ssp."order",
  created_at           timestamptz not null default now(),
  unique (tenant_id, name)
);

create table ssp.tenant_generation (
  tenant_id    text references ssp.tenant,
  generation   bigint not null,
  expected_uri text not null,
  spec_hashes  text[] not null,
  created_at   timestamptz not null default now(),
  primary key (tenant_id, generation)
);

create table ssp.run (
  run_id        text primary key,
  tenant_id     text not null references ssp.tenant,
  generation    bigint not null,
  kind          ssp.run_kind not null,
  state         ssp.run_state not null default 'queued',
  attempt       int not null default 1,
  job_name      text not null,
  workflow_id   text not null,
  order_ids     text[] not null,
  plan_summary  jsonb,
  started_at    timestamptz,
  finished_at   timestamptz,
  error         text,
  artifacts_uri text
);
create index run_tenant_started_idx on ssp.run (tenant_id, started_at desc);

create table ssp.order_event (
  event_id   bigserial primary key,
  order_id   text not null references ssp."order",
  at         timestamptz not null default now(),
  actor      text not null,
  from_state ssp.order_state,
  to_state   ssp.order_state,
  type       text not null,
  detail     jsonb
);
create index order_event_order_idx on ssp.order_event (order_id, event_id);

create table ssp.drift_finding (
  finding_id           text primary key,
  tenant_id            text not null references ssp.tenant,
  resource_instance_id text references ssp.resource_instance,
  class                ssp.drift_class not null,
  detail               jsonb not null,
  detected_at          timestamptz not null default now(),
  resolved_at          timestamptz,
  resolution           text
);

create table ssp.control_flag (
  scope   text primary key,
  paused  boolean not null default false,
  reason  text,
  set_by  text not null,
  set_at  timestamptz not null default now()
);

create table ssp.audit_event (
  audit_id     bigserial primary key,
  at           timestamptz not null default now(),
  actor        text not null,
  action       text not null,
  subject_type text not null,
  subject_id   text not null,
  before_hash  text,
  after_hash   text,
  detail       jsonb,
  request_id   text
);
create index audit_event_subject_idx on ssp.audit_event (subject_type, subject_id, at desc);

-- +goose Down
drop schema if exists ssp cascade;
