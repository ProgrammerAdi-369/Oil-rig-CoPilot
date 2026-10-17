export const backendContracts = [
  {
    name: "well_status",
    method: "GET",
    route: "/api/wells/:wellId/status",
    purpose:
      "Compute live producing state, last inspection, corrections, evidence, and reasons.",
    response:
      "{ wellId, producing, status, reason, evidence, correctedAt, source }",
  },
  {
    name: "find_wells",
    method: "GET",
    route: "/api/wells/search",
    purpose:
      "Return wells by production state, area, well type, and reason filters.",
    response: "{ rows, evidence, visual, window }",
  },
  {
    name: "downtime",
    method: "GET",
    route: "/api/metrics/downtime",
    purpose:
      "Compute downtime by well, area, or month using derived inspection logic.",
    response: "{ rows, totalDays, evidence, visual }",
  },
  {
    name: "spills",
    method: "GET",
    route: "/api/spills",
    purpose:
      "Return real spill data after correction overlays and compliance-based classification.",
    response: "{ rows, volume, class, evidence, visual }",
  },
  {
    name: "compliance",
    method: "GET",
    route: "/api/compliance",
    purpose:
      "List rule breaches, pending actions, SLA deadlines, and evidence-backed details.",
    response: "{ rows, counts, status, evidence }",
  },
  {
    name: "recall",
    method: "GET",
    route: "/api/memory/recall",
    purpose:
      "Retrieve private memory for the current user without leaking another operator's context.",
    response: "{ conversations, entities, empty }",
  },
  {
    name: "correct_value",
    method: "POST",
    route: "/api/values/correct",
    purpose:
      "Apply a correction while preserving the original value and author metadata.",
    response: "{ before, after, conflict, status, auditTrail }",
  },
  {
    name: "add_type_rule",
    method: "POST",
    route: "/api/rules/type",
    purpose:
      "Add a well-type scoped rule that overrides global defaults for the relevant asset class.",
    response: "{ rule, scope, appliedTo, author }",
  },
];

export const backendStatus = {
  service: "Asset Intelligence Copilot",
  version: "v0.5.0",
  engine: "SQLite + deterministic query tools + retrieval layer",
  status: "ready-for-backend-connection",
  dataContract: "{ rows, evidence, visual, window }",
};

export const backendApi = {
  async getHealth() {
    return {
      ok: true,
      data: backendStatus,
    };
  },

  async getContracts() {
    return {
      ok: true,
      data: backendContracts,
    };
  },

  async getRulebook() {
    return {
      ok: true,
      data: [
        "well_status",
        "downtime",
        "spills",
        "compliance",
        "memory",
        "corrections",
      ],
    };
  },
};
