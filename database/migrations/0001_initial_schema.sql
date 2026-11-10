-- PILO initial schema. SQLite >= 3.37 with JSON functions. No FTS5.
-- Transaction ownership belongs to the runner. Enable foreign_keys before BEGIN.
-- Do not use executescript inside an existing transaction; execute parsed statements.
-- This migration intentionally fails on reapplication; the runner checks its checksum.
CREATE TABLE SchemaMigration (
    migration_id TEXT PRIMARY KEY NOT NULL,
    version INTEGER NOT NULL UNIQUE
        CHECK (version > 0),
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    execution_time_ms INTEGER NOT NULL
        CHECK (execution_time_ms >= 0),
    applied_by TEXT NOT NULL,
    core_version TEXT NOT NULL,
    description TEXT,
    metadata TEXT
        CHECK (
            metadata IS NULL
            OR json_valid(metadata)
        )
) STRICT;

CREATE TABLE Principal (
    principal_id TEXT PRIMARY KEY NOT NULL,
    principal_type TEXT NOT NULL
        CHECK (principal_type IN (
            'USER',
            'SYSTEM',
            'SERVICE',
            'AGENT'
        )),
    principal_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN (
            'ACTIVE',
            'DISABLED'
        )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE Role (
    role_id TEXT PRIMARY KEY NOT NULL,
    role_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE Permission (
    permission_id TEXT PRIMARY KEY NOT NULL,
    permission_key TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE RolePermission (
    role_id TEXT NOT NULL,
    permission_id TEXT NOT NULL,

    PRIMARY KEY (role_id, permission_id),

    FOREIGN KEY (role_id)
        REFERENCES Role(role_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (permission_id)
        REFERENCES Permission(permission_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE PrincipalRole (
    principal_role_id TEXT PRIMARY KEY NOT NULL,
    principal_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    scope_type TEXT NOT NULL
        CHECK (scope_type IN ('SYSTEM', 'PROJECT')),
    scope_id TEXT,
    granted_at TEXT NOT NULL,
    granted_by TEXT,

    CHECK (
        (scope_type = 'SYSTEM' AND scope_id IS NULL)
        OR
        (scope_type = 'PROJECT' AND scope_id IS NOT NULL)
    ),

    FOREIGN KEY (principal_id)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (role_id)
        REFERENCES Role(role_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (scope_id)
        REFERENCES Project(project_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (granted_by)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE Project (
    project_id TEXT PRIMARY KEY NOT NULL,
    project_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN (
            'ACTIVE',
            'PAUSED',
            'ARCHIVED'
        )),
    root_path TEXT,
    repository_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
) STRICT;

CREATE TABLE KnowledgeSpace (
    space_id TEXT PRIMARY KEY NOT NULL,
    space_type TEXT NOT NULL
        CHECK (space_type IN ('COMMON', 'PROJECT')),
    project_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    CHECK (
        (space_type = 'COMMON' AND project_id IS NULL)
        OR
        (space_type = 'PROJECT' AND project_id IS NOT NULL)
    ),

    FOREIGN KEY (project_id)
        REFERENCES Project(project_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE FileAsset (
    file_id TEXT PRIMARY KEY NOT NULL,
    space_id TEXT NOT NULL,
    logical_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    mime_type TEXT,
    file_category TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN (
            'ACTIVE',
            'MISSING',
            'ARCHIVED',
            'DELETED'
        )),
    current_revision_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (space_id, file_id),

    FOREIGN KEY (space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (file_id, current_revision_id)
        REFERENCES FileRevision(file_id, revision_id)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE FileRevision (
    revision_id TEXT PRIMARY KEY NOT NULL,
    file_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL
        CHECK (revision_number > 0),
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
        CHECK (size_bytes >= 0),
    source_modified_at TEXT,
    observed_at TEXT NOT NULL,
    git_commit_sha TEXT,
    storage_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,

    UNIQUE (file_id, revision_id),
    UNIQUE (file_id, revision_number),

    FOREIGN KEY (file_id)
        REFERENCES FileAsset(file_id)
        ON DELETE RESTRICT,
    UNIQUE (space_id, revision_id),
    FOREIGN KEY (space_id, file_id) REFERENCES FileAsset(space_id, file_id)
) STRICT;

CREATE TABLE FileLocationHistory (
    location_id TEXT PRIMARY KEY NOT NULL,
    file_id TEXT NOT NULL,
    logical_path TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    change_reason TEXT NOT NULL
        CHECK (change_reason IN (
            'REGISTER',
            'MOVE',
            'RENAME'
        )),

    CHECK (
        valid_until IS NULL
        OR valid_until > valid_from
    ),

    FOREIGN KEY (file_id)
        REFERENCES FileAsset(file_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ExtractedArtifact (
    artifact_id TEXT PRIMARY KEY NOT NULL,
    revision_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN (
            'TEXT',
            'TABLE',
            'IMAGE',
            'TRANSCRIPT',
            'METADATA',
            'STRUCTURE'
        )),
    extraction_method TEXT NOT NULL
        CHECK (extraction_method IN (
            'OCR',
            'PARSER',
            'ASR',
            'MANUAL',
            'OTHER'
        )),
    content_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    processor TEXT NOT NULL,
    processor_version TEXT,
    language TEXT,
    metadata TEXT
        CHECK (
            metadata IS NULL
            OR json_valid(metadata)
        ),
    status TEXT NOT NULL DEFAULT 'CREATED'
        CHECK (status IN (
            'CREATED',
            'VALIDATED',
            'REJECTED',
            'STALE'
        )),
    created_at TEXT NOT NULL,

    FOREIGN KEY (revision_id)
        REFERENCES FileRevision(revision_id)
        ON DELETE RESTRICT,
    UNIQUE (space_id, artifact_id),
    UNIQUE (space_id, revision_id, artifact_id),
    FOREIGN KEY (space_id, revision_id) REFERENCES FileRevision(space_id, revision_id)
) STRICT;

CREATE TABLE Evidence (
    evidence_id TEXT PRIMARY KEY NOT NULL,
    space_id TEXT NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN (
            'FILE',
            'WEB',
            'DATABASE',
            'USER_INPUT',
            'EXTERNAL'
        )),
    source_ref TEXT NOT NULL,
    revision_id TEXT,
    artifact_id TEXT,
    locator TEXT
        CHECK (
            locator IS NULL
            OR json_valid(locator)
        ),
    content_excerpt TEXT,
    content_hash TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    verification_status TEXT NOT NULL
        DEFAULT 'UNVERIFIED'
        CHECK (verification_status IN (
            'UNVERIFIED',
            'VERIFIED',
            'INVALID',
            'STALE'
        )),

    UNIQUE (space_id, evidence_id),

    FOREIGN KEY (space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (revision_id)
        REFERENCES FileRevision(revision_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (artifact_id)
        REFERENCES ExtractedArtifact(artifact_id)
        ON DELETE RESTRICT,
    CHECK (artifact_id IS NULL OR revision_id IS NOT NULL),
    CHECK (source_type <> 'FILE' OR revision_id IS NOT NULL),
    FOREIGN KEY (space_id, revision_id) REFERENCES FileRevision(space_id, revision_id),
    FOREIGN KEY (space_id, revision_id, artifact_id) REFERENCES ExtractedArtifact(space_id, revision_id, artifact_id)
) STRICT;

CREATE TABLE Claim (
    claim_id TEXT PRIMARY KEY NOT NULL,
    space_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    claim_type TEXT NOT NULL
        CHECK (claim_type IN (
            'FACT',
            'INFERENCE',
            'HYPOTHESIS',
            'OPINION'
        )),
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN (
            'PROPOSED',
            'UNDER_REVIEW',
            'SUPPORTED',
            'CONTRADICTED',
            'UNRESOLVED',
            'REJECTED'
        )),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (space_id, claim_id),

    FOREIGN KEY (space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (created_by)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ClaimEvidence (
    space_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    relation TEXT NOT NULL
        CHECK (relation IN (
            'SUPPORTS',
            'CONTRADICTS',
            'CONTEXT'
        )),
    assessment TEXT,
    created_at TEXT NOT NULL,

    PRIMARY KEY (claim_id, evidence_id),

    FOREIGN KEY (space_id, claim_id)
        REFERENCES Claim(space_id, claim_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (space_id, evidence_id)
        REFERENCES Evidence(space_id, evidence_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE Execution (
    execution_id TEXT PRIMARY KEY NOT NULL,
    scope_type TEXT NOT NULL
        CHECK (scope_type IN ('SYSTEM', 'PROJECT')),
    project_id TEXT,
    parent_execution_id TEXT,
    actor_type TEXT NOT NULL
        CHECK (actor_type IN (
            'USER',
            'ORCHESTRATOR',
            'SKILL',
            'SYSTEM'
        )),
    actor_id TEXT NOT NULL,
    execution_type TEXT NOT NULL,
    request_ref TEXT,
    status TEXT NOT NULL DEFAULT 'RECEIVED'
        CHECK (status IN (
            'RECEIVED',
            'ANALYZING',
            'PLANNING',
            'READY',
            'WAITING_APPROVAL',
            'RUNNING',
            'VERIFYING',
            'COMPLETED',
            'FAILED',
            'CANCELLED',
            'PAUSED',
            'BLOCKED'
        )),
    priority INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    CHECK (
        (scope_type = 'SYSTEM' AND project_id IS NULL)
        OR
        (scope_type = 'PROJECT' AND project_id IS NOT NULL)
    ),

    FOREIGN KEY (project_id)
        REFERENCES Project(project_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (parent_execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (actor_id)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ExecutionStep (
    step_id TEXT PRIMARY KEY NOT NULL,
    execution_id TEXT NOT NULL,
    step_number INTEGER NOT NULL
        CHECK (step_number > 0),
    step_key TEXT NOT NULL,
    step_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING',
            'READY',
            'RUNNING',
            'WAITING_APPROVAL',
            'COMPLETED',
            'FAILED',
            'SKIPPED',
            'CANCELLED'
        )),
    input_ref TEXT,
    output_ref TEXT,
    started_at TEXT,
    completed_at TEXT,
    error_ref TEXT,

    UNIQUE (execution_id, step_id),
    UNIQUE (execution_id, step_number),
    UNIQUE (execution_id, step_key),

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ExecutionStepDependency (
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    depends_on_step_id TEXT NOT NULL,

    PRIMARY KEY (
        execution_id,
        step_id,
        depends_on_step_id
    ),

    CHECK (step_id <> depends_on_step_id),

    FOREIGN KEY (execution_id, step_id)
        REFERENCES ExecutionStep(
            execution_id, step_id
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (
        execution_id,
        depends_on_step_id
    )
        REFERENCES ExecutionStep(
            execution_id, step_id
        )
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE AnalysisResult (
    analysis_id TEXT PRIMARY KEY NOT NULL,
    execution_id TEXT NOT NULL,
    step_id TEXT,
    analysis_type TEXT NOT NULL,
    analysis_method TEXT NOT NULL
        CHECK (analysis_method IN (
            'CODE',
            'AI',
            'HYBRID',
            'MANUAL'
        )),
    processor TEXT NOT NULL,
    processor_version TEXT,
    model_provider TEXT,
    model_name TEXT,
    prompt_version TEXT,
    skill_id TEXT,
    skill_version TEXT,
    input_hash TEXT NOT NULL,
    output_ref TEXT,
    output_hash TEXT,
    output_size_bytes INTEGER
        CHECK (
            output_size_bytes IS NULL
            OR output_size_bytes >= 0
        ),
    schema_version TEXT,
    status TEXT NOT NULL DEFAULT 'CREATED'
        CHECK (status IN ('CREATED','RUNNING','COMPLETED','FAILED','CANCELLED')),
    validation_status TEXT NOT NULL DEFAULT 'NOT_VALIDATED'
        CHECK (validation_status IN ('NOT_VALIDATED','VALID','INVALID','PARTIAL')),
    created_at TEXT NOT NULL,

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (execution_id, step_id)
        REFERENCES ExecutionStep(
            execution_id, step_id
        )
        ON DELETE RESTRICT,
    UNIQUE (execution_id, analysis_id)
) STRICT;

CREATE TABLE AnalysisInput (
    analysis_input_id TEXT PRIMARY KEY NOT NULL,
    analysis_id TEXT NOT NULL,
    input_type TEXT NOT NULL
        CHECK (input_type IN (
            'FILE_REVISION',
            'EXTRACTED_ARTIFACT',
            'EVIDENCE',
            'KNOWLEDGE_VERSION',
            'ANALYSIS_RESULT',
            'USER_INPUT',
            'EXTERNAL_REFERENCE'
        )),
    input_ref TEXT NOT NULL,
    source_space_id TEXT,
    resolved_version_ref TEXT,
    input_hash TEXT NOT NULL,
    input_role TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (analysis_id)
        REFERENCES AnalysisResult(analysis_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (source_space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE AnalysisEvidence (
    analysis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    usage_role TEXT NOT NULL,
    created_at TEXT NOT NULL,

    PRIMARY KEY (analysis_id, evidence_id),

    FOREIGN KEY (analysis_id)
        REFERENCES AnalysisResult(analysis_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (evidence_id)
        REFERENCES Evidence(evidence_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE AnalysisClaim (
    analysis_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    relation_type TEXT NOT NULL
        CHECK (relation_type IN (
            'GENERATED',
            'EVALUATED',
            'SUPPORTED',
            'CHALLENGED'
        )),
    created_at TEXT NOT NULL,

    PRIMARY KEY (analysis_id, claim_id),

    FOREIGN KEY (analysis_id)
        REFERENCES AnalysisResult(analysis_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (claim_id)
        REFERENCES Claim(claim_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ModelInvocation (
    invocation_id TEXT PRIMARY KEY NOT NULL,
    analysis_id TEXT,
    execution_id TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    request_hash TEXT,
    response_hash TEXT,
    input_tokens INTEGER
        CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER
        CHECK (output_tokens IS NULL OR output_tokens >= 0),
    cached_input_tokens INTEGER
        CHECK (
            cached_input_tokens IS NULL
            OR cached_input_tokens >= 0
        ),
    estimated_cost_decimal TEXT,
    actual_cost_decimal TEXT,
    currency TEXT,
    latency_ms INTEGER
        CHECK (latency_ms IS NULL OR latency_ms >= 0),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (analysis_id)
        REFERENCES AnalysisResult(analysis_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (execution_id, analysis_id) REFERENCES AnalysisResult(execution_id, analysis_id)
) STRICT;

CREATE TABLE KnowledgeItem (
    knowledge_id TEXT PRIMARY KEY NOT NULL,
    space_id TEXT NOT NULL,
    title TEXT NOT NULL,
    knowledge_type TEXT NOT NULL
        CHECK (knowledge_type IN (
            'FACT', 'PROCEDURE', 'RULE',
            'CONCEPT', 'DECISION',
            'LESSON', 'REFERENCE'
        )),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN (
            'ACTIVE', 'ARCHIVED', 'DELETED'
        )),
    current_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (space_id, knowledge_id),

    FOREIGN KEY (space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (knowledge_id, current_version_id)
        REFERENCES KnowledgeVersion(
            knowledge_id, version_id
        )
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (created_by) REFERENCES Principal(principal_id)
) STRICT;

CREATE TABLE KnowledgeVersion (
    version_id TEXT PRIMARY KEY NOT NULL,
    knowledge_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    version_number INTEGER NOT NULL
        CHECK (version_number > 0),
    content_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (review_status IN (
            'DRAFT', 'CANDIDATE', 'VERIFIED',
            'APPROVED', 'REJECTED'
        )),
    change_summary TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,

    UNIQUE (knowledge_id, version_id),
    UNIQUE (knowledge_id, version_number),
    UNIQUE (space_id, version_id),

    FOREIGN KEY (space_id, knowledge_id)
        REFERENCES KnowledgeItem(
            space_id, knowledge_id
        )
        ON DELETE RESTRICT,
    FOREIGN KEY (created_by) REFERENCES Principal(principal_id),
    FOREIGN KEY (approved_by) REFERENCES Principal(principal_id),
    CHECK ((review_status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL) OR (review_status <> 'APPROVED' AND approved_by IS NULL AND approved_at IS NULL))
) STRICT;

CREATE TABLE KnowledgeEvidence (
    space_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    relation TEXT NOT NULL
        CHECK (relation IN (
            'SUPPORTS', 'CONTRADICTS', 'CONTEXT'
        )),
    created_at TEXT NOT NULL,

    PRIMARY KEY (version_id, evidence_id),

    FOREIGN KEY (space_id, version_id)
        REFERENCES KnowledgeVersion(
            space_id, version_id
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (space_id, evidence_id)
        REFERENCES Evidence(
            space_id, evidence_id
        )
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE KnowledgeVersionClaim (
    space_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    relation TEXT NOT NULL
        CHECK (relation IN (
            'BASED_ON', 'INCLUDES', 'EXCLUDES'
        )),
    created_at TEXT NOT NULL,

    PRIMARY KEY (version_id, claim_id),

    FOREIGN KEY (space_id, version_id)
        REFERENCES KnowledgeVersion(
            space_id, version_id
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (space_id, claim_id)
        REFERENCES Claim(
            space_id, claim_id
        )
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE KnowledgeReference (
    reference_id TEXT PRIMARY KEY NOT NULL,
    source_space_id TEXT NOT NULL,
    target_knowledge_id TEXT NOT NULL,
    reference_mode TEXT NOT NULL
        CHECK (reference_mode IN (
            'PINNED', 'LATEST'
        )),
    pinned_version_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,

    CHECK (
        (
            reference_mode = 'PINNED'
            AND pinned_version_id IS NOT NULL
        )
        OR
        (
            reference_mode = 'LATEST'
            AND pinned_version_id IS NULL
        )
    ),

    FOREIGN KEY (source_space_id)
        REFERENCES KnowledgeSpace(space_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (target_knowledge_id)
        REFERENCES KnowledgeItem(knowledge_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (
        target_knowledge_id,
        pinned_version_id
    )
        REFERENCES KnowledgeVersion(
            knowledge_id, version_id
        )
        ON DELETE RESTRICT,
    FOREIGN KEY (created_by) REFERENCES Principal(principal_id)
) STRICT;

CREATE TABLE KnowledgeLineage (
    promotion_id TEXT REFERENCES KnowledgePromotion(promotion_id),
    lineage_id TEXT PRIMARY KEY NOT NULL,
    source_knowledge_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    target_knowledge_id TEXT NOT NULL,
    target_version_id TEXT NOT NULL,
    relation_type TEXT NOT NULL
        CHECK (relation_type IN (
            'PROMOTED_FROM',
            'DERIVED_FROM'
        )),
    created_at TEXT NOT NULL,

    CHECK (source_version_id <> target_version_id),

    FOREIGN KEY (
        source_knowledge_id,
        source_version_id
    )
        REFERENCES KnowledgeVersion(
            knowledge_id, version_id
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (
        target_knowledge_id,
        target_version_id
    )
        REFERENCES KnowledgeVersion(
            knowledge_id, version_id
        )
        ON DELETE RESTRICT,
    UNIQUE (source_version_id, target_version_id, relation_type)
) STRICT;

CREATE TABLE ApprovalRequest (
    approval_context_hash TEXT NOT NULL,
    policy_version_ref TEXT NOT NULL,
    approval_id TEXT PRIMARY KEY NOT NULL,
    execution_id TEXT,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_version_ref TEXT,
    resource_hash TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN (
            'PENDING',
            'CHANGES_REQUESTED',
            'APPROVED',
            'REJECTED',
            'CANCELLED',
            'EXPIRED'
        )),
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT,
    resolved_at TEXT,

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (requested_by)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT,
    CHECK (expires_at IS NULL OR expires_at > requested_at),
    CHECK ((status = 'PENDING' AND resolved_at IS NULL) OR (status <> 'PENDING' AND resolved_at IS NOT NULL))
) STRICT;

CREATE TABLE ApprovalDecision (
    decision_id TEXT PRIMARY KEY NOT NULL,
    approval_id TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN (
            'APPROVE',
            'REJECT',
            'REQUEST_CHANGES'
        )),
    reason TEXT,
    decided_at TEXT NOT NULL,

    FOREIGN KEY (approval_id)
        REFERENCES ApprovalRequest(approval_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (decided_by)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT,
    UNIQUE (approval_id)
) STRICT;

CREATE TABLE AuditEvent (
    event_id TEXT PRIMARY KEY NOT NULL,
    sequence_number INTEGER NOT NULL UNIQUE
        CHECK (sequence_number > 0),
    actor_id TEXT,
    execution_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    event_payload TEXT
        CHECK (
            event_payload IS NULL
            OR json_valid(event_payload)
        ),
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (actor_id)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE AccessPolicy (
    policy_id TEXT PRIMARY KEY NOT NULL,
    policy_key TEXT NOT NULL UNIQUE,
    policy_type TEXT NOT NULL
        CHECK (policy_type IN (
            'PROJECT_ISOLATION',
            'REQUIRE_APPROVAL',
            'DENY_EXTERNAL_TRANSFER',
            'RESOURCE_CLASSIFICATION',
            'EXECUTION_SCOPE'
        )),
    effect TEXT NOT NULL
        CHECK (effect IN (
            'ALLOW', 'DENY', 'REQUIRE_APPROVAL'
        )),
    parameters TEXT NOT NULL
        CHECK (json_valid(parameters)),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    priority INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (created_by)
        REFERENCES Principal(principal_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE ErrorRecord (
    error_id TEXT PRIMARY KEY NOT NULL,
    execution_id TEXT NOT NULL,
    step_id TEXT,
    analysis_id TEXT,
    error_code TEXT,
    error_category TEXT NOT NULL,
    message TEXT NOT NULL,
    fingerprint TEXT,
    retryable INTEGER NOT NULL DEFAULT 0
        CHECK (retryable IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN (
            'OPEN',
            'INVESTIGATING',
            'RESOLVED',
            'IGNORED'
        )),
    details_ref TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,

    FOREIGN KEY (execution_id)
        REFERENCES Execution(execution_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (execution_id, step_id)
        REFERENCES ExecutionStep(
            execution_id, step_id
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (execution_id, analysis_id)
        REFERENCES AnalysisResult(
            execution_id, analysis_id
        )
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE EvidenceLineage (
    lineage_id TEXT PRIMARY KEY NOT NULL,
    source_evidence_id TEXT NOT NULL,
    target_evidence_id TEXT NOT NULL,
    relation_type TEXT NOT NULL
        CHECK (relation_type IN (
            'PROMOTED_FROM',
            'DERIVED_FROM',
            'NORMALIZED_FROM'
        )),
    promotion_id TEXT,
    created_at TEXT NOT NULL,

    CHECK (
        source_evidence_id <> target_evidence_id
    ),

    UNIQUE (
        source_evidence_id,
        target_evidence_id,
        relation_type
    ),

    FOREIGN KEY (source_evidence_id)
        REFERENCES Evidence(evidence_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (target_evidence_id)
        REFERENCES Evidence(evidence_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (promotion_id)
        REFERENCES KnowledgePromotion(promotion_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE AnalysisOutput (
 output_id TEXT PRIMARY KEY NOT NULL,
 analysis_id TEXT NOT NULL REFERENCES AnalysisResult(analysis_id),
 output_type TEXT NOT NULL,
 content_ref TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
) STRICT;

CREATE TABLE KnowledgePromotion (
 promotion_id TEXT PRIMARY KEY NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE,
 source_knowledge_id TEXT NOT NULL,
 source_version_id TEXT NOT NULL,
 target_knowledge_id TEXT,
 target_version_id TEXT,
 approval_id TEXT UNIQUE REFERENCES ApprovalRequest(approval_id),
 requested_by TEXT NOT NULL REFERENCES Principal(principal_id),
 status TEXT NOT NULL DEFAULT 'REQUESTED' CHECK (status IN
 ('REQUESTED','REVIEWING','WAITING_APPROVAL','REJECTED','APPROVED','APPLYING','COMPLETED','FAILED')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK ((target_knowledge_id IS NULL) = (target_version_id IS NULL)),
 CHECK (status <> 'COMPLETED' OR target_version_id IS NOT NULL),
 FOREIGN KEY (source_knowledge_id,source_version_id) REFERENCES KnowledgeVersion(knowledge_id,version_id),
 FOREIGN KEY (target_knowledge_id,target_version_id) REFERENCES KnowledgeVersion(knowledge_id,version_id)
) STRICT;

CREATE UNIQUE INDEX uq_principal_role_system
ON PrincipalRole(principal_id, role_id)
WHERE scope_type = 'SYSTEM';

CREATE UNIQUE INDEX uq_principal_role_project
ON PrincipalRole(principal_id, role_id, scope_id)
WHERE scope_type = 'PROJECT';

CREATE UNIQUE INDEX uq_common_space
ON KnowledgeSpace(space_type)
WHERE space_type = 'COMMON';

CREATE UNIQUE INDEX uq_project_space
ON KnowledgeSpace(project_id)
WHERE space_type = 'PROJECT';

CREATE UNIQUE INDEX uq_file_asset_active_path
ON FileAsset(space_id, logical_path)
WHERE status IN ('ACTIVE', 'MISSING');

CREATE UNIQUE INDEX uq_file_location_current
ON FileLocationHistory(file_id)
WHERE valid_until IS NULL;

CREATE UNIQUE INDEX uq_approval_decision_request
ON ApprovalDecision(approval_id);

CREATE TRIGGER trg_FileRevision_update BEFORE UPDATE ON FileRevision
BEGIN
 SELECT RAISE(ABORT, 'FileRevision is append-only');
END;

CREATE TRIGGER trg_FileRevision_delete BEFORE DELETE ON FileRevision
BEGIN
 SELECT RAISE(ABORT, 'FileRevision is append-only');
END;

CREATE TRIGGER trg_ApprovalDecision_update BEFORE UPDATE ON ApprovalDecision
BEGIN
 SELECT RAISE(ABORT, 'ApprovalDecision is append-only');
END;

CREATE TRIGGER trg_ApprovalDecision_delete BEFORE DELETE ON ApprovalDecision
BEGIN
 SELECT RAISE(ABORT, 'ApprovalDecision is append-only');
END;

CREATE TRIGGER trg_AuditEvent_update BEFORE UPDATE ON AuditEvent
BEGIN
 SELECT RAISE(ABORT, 'AuditEvent is append-only');
END;

CREATE TRIGGER trg_AuditEvent_delete BEFORE DELETE ON AuditEvent
BEGIN
 SELECT RAISE(ABORT, 'AuditEvent is append-only');
END;

CREATE TRIGGER trg_SchemaMigration_update BEFORE UPDATE ON SchemaMigration
BEGIN
 SELECT RAISE(ABORT, 'SchemaMigration is append-only');
END;

CREATE TRIGGER trg_SchemaMigration_delete BEFORE DELETE ON SchemaMigration
BEGIN
 SELECT RAISE(ABORT, 'SchemaMigration is append-only');
END;

CREATE TRIGGER trg_KnowledgeLineage_update BEFORE UPDATE ON KnowledgeLineage
BEGIN
 SELECT RAISE(ABORT, 'KnowledgeLineage is append-only');
END;

CREATE TRIGGER trg_KnowledgeLineage_delete BEFORE DELETE ON KnowledgeLineage
BEGIN
 SELECT RAISE(ABORT, 'KnowledgeLineage is append-only');
END;

CREATE TRIGGER trg_EvidenceLineage_update BEFORE UPDATE ON EvidenceLineage
BEGIN
 SELECT RAISE(ABORT, 'EvidenceLineage is append-only');
END;

CREATE TRIGGER trg_EvidenceLineage_delete BEFORE DELETE ON EvidenceLineage
BEGIN
 SELECT RAISE(ABORT, 'EvidenceLineage is append-only');
END;

CREATE TRIGGER trg_AnalysisOutput_update BEFORE UPDATE ON AnalysisOutput
BEGIN
 SELECT RAISE(ABORT, 'AnalysisOutput is append-only');
END;

CREATE TRIGGER trg_AnalysisOutput_delete BEFORE DELETE ON AnalysisOutput
BEGIN
 SELECT RAISE(ABORT, 'AnalysisOutput is append-only');
END;

CREATE TRIGGER trg_KnowledgeVersion_content BEFORE UPDATE ON KnowledgeVersion
WHEN NEW.version_id IS NOT OLD.version_id OR NEW.knowledge_id IS NOT OLD.knowledge_id OR NEW.space_id IS NOT OLD.space_id OR NEW.version_number IS NOT OLD.version_number OR NEW.content_ref IS NOT OLD.content_ref OR NEW.content_hash IS NOT OLD.content_hash OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at OR NEW.change_summary IS NOT OLD.change_summary
BEGIN
 SELECT RAISE(ABORT, 'KnowledgeVersion content is immutable');
END;

CREATE TRIGGER trg_KnowledgeVersion_delete BEFORE DELETE ON KnowledgeVersion
BEGIN
 SELECT RAISE(ABORT, 'KnowledgeVersion cannot be deleted');
END;

CREATE TRIGGER trg_ExtractedArtifact_content BEFORE UPDATE ON ExtractedArtifact
WHEN NEW.artifact_id IS NOT OLD.artifact_id OR NEW.space_id IS NOT OLD.space_id OR NEW.revision_id IS NOT OLD.revision_id OR NEW.content_ref IS NOT OLD.content_ref OR NEW.content_hash IS NOT OLD.content_hash OR NEW.artifact_type IS NOT OLD.artifact_type OR NEW.extraction_method IS NOT OLD.extraction_method OR NEW.processor IS NOT OLD.processor OR NEW.processor_version IS NOT OLD.processor_version OR NEW.metadata IS NOT OLD.metadata OR NEW.created_at IS NOT OLD.created_at
BEGIN
 SELECT RAISE(ABORT, 'ExtractedArtifact content is immutable');
END;

CREATE TRIGGER trg_ExtractedArtifact_delete BEFORE DELETE ON ExtractedArtifact
BEGIN
 SELECT RAISE(ABORT, 'ExtractedArtifact cannot be deleted');
END;

CREATE TRIGGER trg_Evidence_content BEFORE UPDATE ON Evidence
WHEN NEW.evidence_id IS NOT OLD.evidence_id OR NEW.space_id IS NOT OLD.space_id OR NEW.source_type IS NOT OLD.source_type OR NEW.source_ref IS NOT OLD.source_ref OR NEW.revision_id IS NOT OLD.revision_id OR NEW.artifact_id IS NOT OLD.artifact_id OR NEW.locator IS NOT OLD.locator OR NEW.content_excerpt IS NOT OLD.content_excerpt OR NEW.content_hash IS NOT OLD.content_hash OR NEW.collected_at IS NOT OLD.collected_at
BEGIN
 SELECT RAISE(ABORT, 'Evidence content is immutable');
END;

CREATE TRIGGER trg_Evidence_delete BEFORE DELETE ON Evidence
BEGIN
 SELECT RAISE(ABORT, 'Evidence cannot be deleted');
END;

CREATE TRIGGER trg_Claim_content BEFORE UPDATE ON Claim
WHEN NEW.claim_id IS NOT OLD.claim_id OR NEW.space_id IS NOT OLD.space_id OR NEW.statement IS NOT OLD.statement OR NEW.claim_type IS NOT OLD.claim_type OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at
BEGIN
 SELECT RAISE(ABORT, 'Claim content is immutable');
END;

CREATE TRIGGER trg_Claim_delete BEFORE DELETE ON Claim
BEGIN
 SELECT RAISE(ABORT, 'Claim cannot be deleted');
END;

CREATE TRIGGER trg_analysis_final BEFORE UPDATE ON AnalysisResult
WHEN OLD.status IN ('COMPLETED','FAILED','CANCELLED')
BEGIN
 SELECT RAISE(ABORT, 'Final analysis is immutable');
END;

CREATE TRIGGER trg_current_insert BEFORE INSERT ON KnowledgeItem
WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.knowledge_id=NEW.knowledge_id AND v.space_id=NEW.space_id AND v.version_id=NEW.current_version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT, 'Current version must be approved and belong to item');
END;

CREATE TRIGGER trg_current_update BEFORE UPDATE ON KnowledgeItem
WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.knowledge_id=NEW.knowledge_id AND v.space_id=NEW.space_id AND v.version_id=NEW.current_version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT, 'Current version must be approved and belong to item');
END;

CREATE TRIGGER trg_approved_final BEFORE UPDATE ON KnowledgeVersion
WHEN OLD.review_status='APPROVED' AND (NEW.review_status IS NOT OLD.review_status OR NEW.approved_by IS NOT OLD.approved_by OR NEW.approved_at IS NOT OLD.approved_at)
BEGIN
 SELECT RAISE(ABORT, 'Approved review is final');
END;

CREATE TRIGGER trg_request_initial BEFORE INSERT ON ApprovalRequest
WHEN NEW.status <> 'PENDING'
BEGIN
 SELECT RAISE(ABORT, 'New request must be pending');
END;

CREATE TRIGGER trg_request_content BEFORE UPDATE ON ApprovalRequest
WHEN NEW.approval_id IS NOT OLD.approval_id OR NEW.execution_id IS NOT OLD.execution_id OR NEW.resource_type IS NOT OLD.resource_type OR NEW.resource_id IS NOT OLD.resource_id OR NEW.resource_version_ref IS NOT OLD.resource_version_ref OR NEW.resource_hash IS NOT OLD.resource_hash OR NEW.action IS NOT OLD.action OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NOT OLD.expires_at OR NEW.policy_version_ref IS NOT OLD.policy_version_ref OR NEW.approval_context_hash IS NOT OLD.approval_context_hash
BEGIN
 SELECT RAISE(ABORT, 'Approval scope is immutable');
END;

CREATE TRIGGER trg_request_state BEFORE UPDATE ON ApprovalRequest
WHEN OLD.status <> 'PENDING' OR (NEW.status IN ('APPROVED','REJECTED','CHANGES_REQUESTED') AND NOT EXISTS (SELECT 1 FROM ApprovalDecision d WHERE d.approval_id=NEW.approval_id AND NEW.status=CASE d.decision WHEN 'APPROVE' THEN 'APPROVED' WHEN 'REQUEST_CHANGES' THEN 'CHANGES_REQUESTED' ELSE 'REJECTED' END))
BEGIN
 SELECT RAISE(ABORT, 'Invalid approval transition');
END;

CREATE TRIGGER trg_decision_pending BEFORE INSERT ON ApprovalDecision
WHEN NOT EXISTS (SELECT 1 FROM ApprovalRequest r WHERE r.approval_id=NEW.approval_id AND r.status='PENDING' AND NEW.decided_at>=r.requested_at AND (r.expires_at IS NULL OR NEW.decided_at<r.expires_at))
BEGIN
 SELECT RAISE(ABORT, 'Request is not pending or decision expired');
END;

CREATE TRIGGER trg_decision_resolve AFTER INSERT ON ApprovalDecision BEGIN
 UPDATE ApprovalRequest SET status=CASE NEW.decision WHEN 'APPROVE' THEN 'APPROVED' WHEN 'REQUEST_CHANGES' THEN 'CHANGES_REQUESTED' ELSE 'REJECTED' END,
 resolved_at=NEW.decided_at WHERE approval_id=NEW.approval_id;
END;

CREATE TRIGGER trg_promotion_insert BEFORE INSERT ON KnowledgePromotion
WHEN NEW.status IN ('APPROVED','APPLYING','COMPLETED')
BEGIN
 SELECT CASE WHEN NOT EXISTS (
 SELECT 1 FROM ApprovalRequest r JOIN ApprovalDecision d USING(approval_id)
 WHERE r.approval_id=NEW.approval_id AND r.status='APPROVED' AND d.decision='APPROVE'
 AND r.resource_type='KNOWLEDGE_PROMOTION' AND r.resource_id=NEW.promotion_id
 AND r.resource_version_ref=NEW.source_version_id AND r.action='PROMOTE'
 AND r.resource_hash=(SELECT content_hash FROM KnowledgeVersion WHERE version_id=NEW.source_version_id)
 ) THEN RAISE(ABORT,'Promotion requires matching approval') END;
 SELECT CASE WHEN NEW.status='COMPLETED' AND NOT EXISTS (
 SELECT 1 FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id)
 JOIN KnowledgeLineage l ON l.target_version_id=v.version_id
 WHERE v.version_id=NEW.target_version_id AND s.space_type='COMMON' AND v.review_status='APPROVED'
 AND l.promotion_id=NEW.promotion_id AND l.source_version_id=NEW.source_version_id
 AND l.source_knowledge_id=NEW.source_knowledge_id AND l.target_knowledge_id=NEW.target_knowledge_id
 AND l.relation_type='PROMOTED_FROM'
 ) THEN RAISE(ABORT,'Completed promotion requires approved common target and lineage') END;
END;

CREATE TRIGGER trg_promotion_update BEFORE UPDATE ON KnowledgePromotion
WHEN NEW.status IN ('APPROVED','APPLYING','COMPLETED')
BEGIN
 SELECT CASE WHEN NOT EXISTS (
 SELECT 1 FROM ApprovalRequest r JOIN ApprovalDecision d USING(approval_id)
 WHERE r.approval_id=NEW.approval_id AND r.status='APPROVED' AND d.decision='APPROVE'
 AND r.resource_type='KNOWLEDGE_PROMOTION' AND r.resource_id=NEW.promotion_id
 AND r.resource_version_ref=NEW.source_version_id AND r.action='PROMOTE'
 AND r.resource_hash=(SELECT content_hash FROM KnowledgeVersion WHERE version_id=NEW.source_version_id)
 ) THEN RAISE(ABORT,'Promotion requires matching approval') END;
 SELECT CASE WHEN NEW.status='COMPLETED' AND NOT EXISTS (
 SELECT 1 FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id)
 JOIN KnowledgeLineage l ON l.target_version_id=v.version_id
 WHERE v.version_id=NEW.target_version_id AND s.space_type='COMMON' AND v.review_status='APPROVED'
 AND l.promotion_id=NEW.promotion_id AND l.source_version_id=NEW.source_version_id
 AND l.source_knowledge_id=NEW.source_knowledge_id AND l.target_knowledge_id=NEW.target_knowledge_id
 AND l.relation_type='PROMOTED_FROM'
 ) THEN RAISE(ABORT,'Completed promotion requires approved common target and lineage') END;
END;

CREATE TRIGGER trg_promotion_final BEFORE UPDATE ON KnowledgePromotion
WHEN OLD.status='COMPLETED'
BEGIN
 SELECT RAISE(ABORT,'Completed promotion is immutable');
END;

CREATE TRIGGER trg_promotion_scope BEFORE UPDATE ON KnowledgePromotion
WHEN NEW.source_version_id IS NOT OLD.source_version_id OR NEW.source_knowledge_id IS NOT OLD.source_knowledge_id OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.promotion_id IS NOT OLD.promotion_id
BEGIN
 SELECT RAISE(ABORT,'Promotion source is immutable');
END;

CREATE TRIGGER trg_owner_FileAsset_space_id BEFORE UPDATE ON FileAsset
WHEN NEW.space_id IS NOT OLD.space_id
BEGIN
 SELECT RAISE(ABORT,'Ownership is immutable');
END;

CREATE TRIGGER trg_owner_KnowledgeItem_space_id BEFORE UPDATE ON KnowledgeItem
WHEN NEW.space_id IS NOT OLD.space_id
BEGIN
 SELECT RAISE(ABORT,'Ownership is immutable');
END;

CREATE TRIGGER trg_owner_KnowledgeSpace_space_type BEFORE UPDATE ON KnowledgeSpace
WHEN NEW.space_type IS NOT OLD.space_type
BEGIN
 SELECT RAISE(ABORT,'Ownership is immutable');
END;

CREATE TRIGGER trg_owner_KnowledgeSpace_project_id BEFORE UPDATE ON KnowledgeSpace
WHEN NEW.project_id IS NOT OLD.project_id
BEGIN
 SELECT RAISE(ABORT,'Ownership is immutable');
END;
INSERT INTO Principal VALUES ('system','SYSTEM','pilo-system','PILO System','ACTIVE','2026-11-09T00:00:00.000Z','2026-11-09T00:00:00.000Z');
INSERT INTO Role VALUES ('system-role','SYSTEM','System',NULL,'2026-11-09T00:00:00.000Z');
INSERT INTO PrincipalRole VALUES ('system-grant','system','system-role','SYSTEM',NULL,'2026-11-09T00:00:00.000Z','system');
INSERT INTO KnowledgeSpace VALUES ('common','COMMON',NULL,'Common Knowledge',NULL,'ACTIVE','2026-11-09T00:00:00.000Z','2026-11-09T00:00:00.000Z');

-- Keep bootstrap identities stable and preserve the singleton COMMON space.
CREATE TRIGGER trg_common_no_delete BEFORE DELETE ON KnowledgeSpace
WHEN OLD.space_type='COMMON' BEGIN SELECT RAISE(ABORT,'Common space cannot be deleted'); END;
CREATE TRIGGER trg_promotion_project_source BEFORE INSERT ON KnowledgePromotion
WHEN NOT EXISTS (SELECT 1 FROM KnowledgeVersion v JOIN KnowledgeSpace s USING(space_id)
 WHERE v.version_id=NEW.source_version_id AND s.space_type='PROJECT')
BEGIN SELECT RAISE(ABORT,'Promotion source must belong to project space'); END;
CREATE TRIGGER trg_lineage_promotion BEFORE INSERT ON KnowledgeLineage
WHEN NEW.relation_type='PROMOTED_FROM' AND (NEW.promotion_id IS NULL OR NOT EXISTS (
 SELECT 1 FROM KnowledgePromotion p WHERE p.promotion_id=NEW.promotion_id
 AND p.source_knowledge_id=NEW.source_knowledge_id AND p.source_version_id=NEW.source_version_id))
BEGIN SELECT RAISE(ABORT,'Promoted lineage requires matching promotion'); END;
CREATE TRIGGER trg_evidence_lineage_promotion BEFORE INSERT ON EvidenceLineage
WHEN NEW.relation_type='PROMOTED_FROM' AND (NEW.promotion_id IS NULL OR NOT EXISTS (
 SELECT 1 FROM KnowledgePromotion p
 JOIN KnowledgeVersion v ON v.version_id=p.source_version_id
 JOIN Evidence src ON src.evidence_id=NEW.source_evidence_id AND src.space_id=v.space_id
 JOIN Evidence dst ON dst.evidence_id=NEW.target_evidence_id
 JOIN KnowledgeSpace target_space ON target_space.space_id=dst.space_id
 WHERE p.promotion_id=NEW.promotion_id AND target_space.space_type='COMMON'
 AND p.status IN ('APPROVED','APPLYING','COMPLETED')))
BEGIN SELECT RAISE(ABORT,'Promoted evidence lineage requires approved project-to-common promotion'); END;

CREATE INDEX ix_RolePermission_fk_0 ON RolePermission(permission_id);
CREATE INDEX ix_PrincipalRole_fk_0 ON PrincipalRole(granted_by);
CREATE INDEX ix_PrincipalRole_fk_1 ON PrincipalRole(scope_id);
CREATE INDEX ix_PrincipalRole_fk_2 ON PrincipalRole(role_id);
CREATE INDEX ix_PrincipalRole_fk_3 ON PrincipalRole(principal_id);
CREATE INDEX ix_KnowledgeSpace_fk_0 ON KnowledgeSpace(project_id);
CREATE INDEX ix_FileAsset_fk_0 ON FileAsset(file_id, current_revision_id);
CREATE INDEX ix_FileRevision_fk_0 ON FileRevision(space_id, file_id);
CREATE INDEX ix_FileLocationHistory_fk_0 ON FileLocationHistory(file_id);
CREATE INDEX ix_ExtractedArtifact_fk_1 ON ExtractedArtifact(revision_id);
CREATE INDEX ix_Evidence_fk_0 ON Evidence(space_id, revision_id, artifact_id);
CREATE INDEX ix_Evidence_fk_2 ON Evidence(artifact_id);
CREATE INDEX ix_Evidence_fk_3 ON Evidence(revision_id);
CREATE INDEX ix_Claim_fk_0 ON Claim(created_by);
CREATE INDEX ix_ClaimEvidence_fk_0 ON ClaimEvidence(space_id, evidence_id);
CREATE INDEX ix_ClaimEvidence_fk_1 ON ClaimEvidence(space_id, claim_id);
CREATE INDEX ix_Execution_fk_0 ON Execution(actor_id);
CREATE INDEX ix_Execution_fk_1 ON Execution(parent_execution_id);
CREATE INDEX ix_Execution_fk_2 ON Execution(project_id);
CREATE INDEX ix_ExecutionStepDependency_fk_0 ON ExecutionStepDependency(execution_id, depends_on_step_id);
CREATE INDEX ix_AnalysisResult_fk_0 ON AnalysisResult(execution_id, step_id);
CREATE INDEX ix_AnalysisInput_fk_0 ON AnalysisInput(source_space_id);
CREATE INDEX ix_AnalysisInput_fk_1 ON AnalysisInput(analysis_id);
CREATE INDEX ix_AnalysisEvidence_fk_0 ON AnalysisEvidence(evidence_id);
CREATE INDEX ix_AnalysisClaim_fk_0 ON AnalysisClaim(claim_id);
CREATE INDEX ix_ModelInvocation_fk_0 ON ModelInvocation(execution_id, analysis_id);
CREATE INDEX ix_ModelInvocation_fk_2 ON ModelInvocation(analysis_id);
CREATE INDEX ix_KnowledgeItem_fk_0 ON KnowledgeItem(created_by);
CREATE INDEX ix_KnowledgeItem_fk_1 ON KnowledgeItem(knowledge_id, current_version_id);
CREATE INDEX ix_KnowledgeVersion_fk_0 ON KnowledgeVersion(approved_by);
CREATE INDEX ix_KnowledgeVersion_fk_1 ON KnowledgeVersion(created_by);
CREATE INDEX ix_KnowledgeVersion_fk_2 ON KnowledgeVersion(space_id, knowledge_id);
CREATE INDEX ix_KnowledgeEvidence_fk_0 ON KnowledgeEvidence(space_id, evidence_id);
CREATE INDEX ix_KnowledgeEvidence_fk_1 ON KnowledgeEvidence(space_id, version_id);
CREATE INDEX ix_KnowledgeVersionClaim_fk_0 ON KnowledgeVersionClaim(space_id, claim_id);
CREATE INDEX ix_KnowledgeVersionClaim_fk_1 ON KnowledgeVersionClaim(space_id, version_id);
CREATE INDEX ix_KnowledgeReference_fk_0 ON KnowledgeReference(created_by);
CREATE INDEX ix_KnowledgeReference_fk_1 ON KnowledgeReference(target_knowledge_id, pinned_version_id);
CREATE INDEX ix_KnowledgeReference_fk_3 ON KnowledgeReference(source_space_id);
CREATE INDEX ix_KnowledgeLineage_fk_0 ON KnowledgeLineage(target_knowledge_id, target_version_id);
CREATE INDEX ix_KnowledgeLineage_fk_1 ON KnowledgeLineage(source_knowledge_id, source_version_id);
CREATE INDEX ix_KnowledgeLineage_fk_2 ON KnowledgeLineage(promotion_id);
CREATE INDEX ix_ApprovalRequest_fk_0 ON ApprovalRequest(requested_by);
CREATE INDEX ix_ApprovalRequest_fk_1 ON ApprovalRequest(execution_id);
CREATE INDEX ix_ApprovalDecision_fk_0 ON ApprovalDecision(decided_by);
CREATE INDEX ix_AuditEvent_fk_0 ON AuditEvent(execution_id);
CREATE INDEX ix_AuditEvent_fk_1 ON AuditEvent(actor_id);
CREATE INDEX ix_AccessPolicy_fk_0 ON AccessPolicy(created_by);
CREATE INDEX ix_ErrorRecord_fk_0 ON ErrorRecord(execution_id, analysis_id);
CREATE INDEX ix_ErrorRecord_fk_1 ON ErrorRecord(execution_id, step_id);
CREATE INDEX ix_EvidenceLineage_fk_0 ON EvidenceLineage(promotion_id);
CREATE INDEX ix_EvidenceLineage_fk_1 ON EvidenceLineage(target_evidence_id);
CREATE INDEX ix_AnalysisOutput_fk_0 ON AnalysisOutput(analysis_id);
CREATE INDEX ix_KnowledgePromotion_fk_0 ON KnowledgePromotion(target_knowledge_id, target_version_id);
CREATE INDEX ix_KnowledgePromotion_fk_1 ON KnowledgePromotion(source_knowledge_id, source_version_id);
CREATE INDEX ix_KnowledgePromotion_fk_2 ON KnowledgePromotion(requested_by);
CREATE INDEX ix_execution_status_created ON Execution(status,created_at);
CREATE INDEX ix_error_fingerprint ON ErrorRecord(fingerprint,created_at);
CREATE INDEX ix_knowledge_review ON KnowledgeVersion(space_id,review_status,created_at);
CREATE INDEX ix_approval_pending ON ApprovalRequest(status,expires_at) WHERE status='PENDING';
CREATE INDEX ix_audit_resource ON AuditEvent(resource_type,resource_id,sequence_number);


-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeEvidence_approved_insert
BEFORE INSERT ON KnowledgeEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=NEW.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeEvidence_approved_delete
BEFORE DELETE ON KnowledgeEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=OLD.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeEvidence_approved_update
BEFORE UPDATE ON KnowledgeEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=OLD.version_id AND v.review_status='APPROVED') OR EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=NEW.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeVersionClaim_approved_insert
BEFORE INSERT ON KnowledgeVersionClaim
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=NEW.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeVersionClaim_approved_delete
BEFORE DELETE ON KnowledgeVersionClaim
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=OLD.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Freeze direct provenance membership at approval, including moves and REPLACE.
CREATE TRIGGER trg_KnowledgeVersionClaim_approved_update
BEFORE UPDATE ON KnowledgeVersionClaim
WHEN EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=OLD.version_id AND v.review_status='APPROVED') OR EXISTS (SELECT 1 FROM KnowledgeVersion v WHERE v.version_id=NEW.version_id AND v.review_status='APPROVED')
BEGIN
 SELECT RAISE(ABORT,'Approved knowledge associations are immutable');
END;

-- Preserve claim support once included in any approved knowledge version.
CREATE TRIGGER trg_ClaimEvidence_approved_insert BEFORE INSERT ON ClaimEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersionClaim c JOIN KnowledgeVersion v USING(version_id) WHERE c.claim_id=NEW.claim_id AND v.review_status='APPROVED')
BEGIN SELECT RAISE(ABORT,'Approved claim evidence is immutable'); END;

-- Preserve claim support once included in any approved knowledge version.
CREATE TRIGGER trg_ClaimEvidence_approved_delete BEFORE DELETE ON ClaimEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersionClaim c JOIN KnowledgeVersion v USING(version_id) WHERE c.claim_id=OLD.claim_id AND v.review_status='APPROVED')
BEGIN SELECT RAISE(ABORT,'Approved claim evidence is immutable'); END;

-- Preserve claim support once included in any approved knowledge version.
CREATE TRIGGER trg_ClaimEvidence_approved_update BEFORE UPDATE ON ClaimEvidence
WHEN EXISTS (SELECT 1 FROM KnowledgeVersionClaim c JOIN KnowledgeVersion v USING(version_id) WHERE c.claim_id=OLD.claim_id AND v.review_status='APPROVED') OR EXISTS (SELECT 1 FROM KnowledgeVersionClaim c JOIN KnowledgeVersion v USING(version_id) WHERE c.claim_id=NEW.claim_id AND v.review_status='APPROVED')
BEGIN SELECT RAISE(ABORT,'Approved claim evidence is immutable'); END;

-- Terminal analysis snapshots preserve their identity and direct input/output/provenance sets.
CREATE TRIGGER trg_analysis_final_delete BEFORE DELETE ON AnalysisResult
WHEN OLD.status IN ('COMPLETED','FAILED','CANCELLED')
BEGIN SELECT RAISE(ABORT,'Terminal analysis history cannot be deleted'); END;

CREATE TRIGGER trg_AnalysisInput_terminal_insert BEFORE INSERT ON AnalysisInput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisInput_terminal_delete BEFORE DELETE ON AnalysisInput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisInput_terminal_update BEFORE UPDATE ON AnalysisInput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED')) OR EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisOutput_terminal_insert BEFORE INSERT ON AnalysisOutput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisOutput_terminal_delete BEFORE DELETE ON AnalysisOutput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisOutput_terminal_update BEFORE UPDATE ON AnalysisOutput
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED')) OR EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisEvidence_terminal_insert BEFORE INSERT ON AnalysisEvidence
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisEvidence_terminal_delete BEFORE DELETE ON AnalysisEvidence
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisEvidence_terminal_update BEFORE UPDATE ON AnalysisEvidence
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED')) OR EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisClaim_terminal_insert BEFORE INSERT ON AnalysisClaim
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisClaim_terminal_delete BEFORE DELETE ON AnalysisClaim
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;

CREATE TRIGGER trg_AnalysisClaim_terminal_update BEFORE UPDATE ON AnalysisClaim
WHEN EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=OLD.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED')) OR EXISTS (SELECT 1 FROM AnalysisResult a WHERE a.analysis_id=NEW.analysis_id AND a.status IN ('COMPLETED','FAILED','CANCELLED'))
BEGIN SELECT RAISE(ABORT,'Terminal analysis child set is immutable'); END;
