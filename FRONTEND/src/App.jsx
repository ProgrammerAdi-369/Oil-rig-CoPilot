import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Bot,
  CalendarRange,
  CheckCheck,
  ChevronDown,
  Circle,
  Copy,
  Database,
  FileText,
  Gauge,
  Home,
  ImagePlus,
  LayoutGrid,
  MapPinned,
  MessageSquareQuote,
  Mic,
  Paperclip,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Thermometer,
  TrendingUp,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { backendApi, backendContracts } from "./services/assetApi";
import "./App.css";

const currentFieldDate = "16 Oct 2026";

const personaOptions = [
  "Production Supervisor (U-101)",
  "Field Inspector (U-201)",
  "HSE Officer (U-301)",
  "Maintenance Tech (U-401)",
];

const areaOptions = ["All Areas", "SW-23", "NE-08", "NW-12", "SE-04"];

const quickActions = [
  "Non-producing wells in SW-23",
  "Spills pending 24h report",
  "T350 temperature anomalies",
  "Downtime summary",
];

const mentionOptions = [
  "@WELL-0001",
  "@Spill-SOP",
  "@SQL-Inspections",
  "@Recent-Thread-07",
];

const slashCommands = [
  "/summary",
  "/downtime-report",
  "/check-spills",
  "/export-csv",
];

const tableRows = [
  {
    well: "WELL-0001",
    status: "At risk",
    temp: "124°C",
    pressure: "42 bar",
    owner: "SW-23",
  },
  {
    well: "WELL-0007",
    status: "Stable",
    temp: "101°C",
    pressure: "30 bar",
    owner: "NW-12",
  },
  {
    well: "T350",
    status: "Critical",
    temp: "132°C",
    pressure: "48 bar",
    owner: "SW-23",
  },
  {
    well: "A-17",
    status: "Warning",
    temp: "119°C",
    pressure: "39 bar",
    owner: "SE-04",
  },
];

const chartSeries = [
  { name: "Mon", value: 81 },
  { name: "Tue", value: 77 },
  { name: "Wed", value: 89 },
  { name: "Thu", value: 86 },
  { name: "Fri", value: 95 },
  { name: "Sat", value: 90 },
];

const tempSeries = [
  { time: "00:00", temp: 102 },
  { time: "04:00", temp: 104 },
  { time: "08:00", temp: 117 },
  { time: "12:00", temp: 124 },
  { time: "16:00", temp: 119 },
  { time: "20:00", temp: 110 },
];

const evidenceLinks = [
  {
    id: "[INS-WELL-0001-14]",
    title: "Inspection note – SW-23 / Well A-17",
    snippet:
      "Separator pressure observed above baseline for 3 consecutive readings after 14:00. Field check requested before next pumping cycle.",
    source: "Inspection report • 16 Oct 2026 • Well A-17",
  },
  {
    id: "[SR-02]",
    title: "Safety review – HSE checklist",
    snippet:
      "Fire-monitoring routine confirmed 92% compliance; open action for emergency skid inspection at NW-12.",
    source: "Safety review • 15 Oct 2026 • HSE operations",
  },
  {
    id: "[T200 Manual]",
    title: "Equipment manual reference",
    snippet:
      "Thermal alarm setpoint for T200 should not exceed 122°C under continuous load. Inspect drive belt integrity.",
    source: "T200 operating manual • Section 7.4",
  },
];

const benchmarkRules = [
  {
    id: "Q1",
    section: "A1",
    title: "Fact exactness",
    requirement:
      "Return exact well IDs, dates, values, and operating states without paraphrasing away the source facts.",
    validation:
      "Fact-check against the retrieved asset, inspection, and sensor records before answering.",
    severity: "critical",
  },
  {
    id: "Q2",
    section: "A1",
    title: "Evidence-linked answer",
    requirement:
      "Every claim must cite the supporting record, SOP, or inspection note in-line.",
    validation:
      "Attach citations such as [INS-WELL-0001-14], [SR-02], or [T200 Manual].",
    severity: "high",
  },
  {
    id: "Q3",
    section: "A1",
    title: "Ground-truth date matching",
    requirement:
      "Dates must match the request window and the last validated update timestamp.",
    validation:
      "Use the exact field date or report date as the anchor when comparing operational windows.",
    severity: "high",
  },
  {
    id: "Q4",
    section: "A1",
    title: "Operational threshold checks",
    requirement:
      "Threshold-based rules such as temperature, pressure, and downtime must map to approved limits.",
    validation:
      "Cross-check alarms against manual thresholds before presenting a risk state.",
    severity: "critical",
  },
  {
    id: "Q5",
    section: "A1",
    title: "Asset status confidence",
    requirement:
      "Status summaries must explain whether the state is confirmed, probable, or inferred.",
    validation:
      "Differentiate between observed sensor data and analyst interpretation.",
    severity: "medium",
  },
  {
    id: "Q6",
    section: "A1",
    title: "Visual format selection",
    requirement:
      "If the user asks for a table, chart, map, or card, render the matching visual component inline.",
    validation:
      "Use a table for multi-row asset data, a chart for trend analysis, and a map for location context.",
    severity: "medium",
  },
  {
    id: "Q7",
    section: "A2",
    title: "User memory carry-forward",
    requirement:
      "Remember the operator's recent context, preference, and area filters across the current session.",
    validation:
      "Persist the active persona, area, and recent thread context in memory for follow-up prompts.",
    severity: "medium",
  },
  {
    id: "Q8",
    section: "A2",
    title: "Feedback loop",
    requirement:
      "Operator corrections must be reflected in the next answer and in the relevant UI state.",
    validation:
      "When a user updates a record or overrides a metric, refresh the cached state and re-render the output.",
    severity: "high",
  },
  {
    id: "Q9",
    section: "A2",
    title: "Branch conversation continuity",
    requirement:
      "When a user branches a thread, the system must preserve the original intent and keep the new branch clearly isolated.",
    validation:
      "Keep the parent thread intact and annotate the branching action in the conversation history.",
    severity: "medium",
  },
  {
    id: "Q10",
    section: "B1",
    title: "Multi-user context isolation",
    requirement:
      "Responses must respect the active user identity and persona-specific privileges.",
    validation:
      "Do not leak internal data from a different operator role or area context into the current response.",
    severity: "critical",
  },
  {
    id: "Q11",
    section: "B1",
    title: "Privacy guardrails",
    requirement:
      "Do not surface protected notes, private comments, or restricted HSE details without the right access level.",
    validation:
      "Mask or redact sensitive content unless the current persona has explicit permission.",
    severity: "critical",
  },
  {
    id: "Q12",
    section: "B1",
    title: "Conflict escalation",
    requirement:
      "When user notes conflict with sensor data, prioritize the verified source and call out the discrepancy.",
    validation:
      "Display the conflict and the evidence-backed recommendation instead of silently choosing one side.",
    severity: "high",
  },
  {
    id: "Q13",
    section: "B1",
    title: "Cross-area safety check",
    requirement:
      "The answer must not ignore a related safety issue in a neighboring area when the impact is relevant.",
    validation:
      "If a spill or thermal risk is adjacent, flag the broader operational exposure clearly.",
    severity: "high",
  },
  {
    id: "Q14",
    section: "B1",
    title: "Access-right audit trail",
    requirement:
      "Actions that access protected fields should be logged and visible in the assistant reasoning trace.",
    validation:
      "Expose the retrieval pipeline or permission check in the execution ladder for auditability.",
    severity: "medium",
  },
  {
    id: "Q15",
    section: "B2",
    title: "Multi-user concurrency",
    requirement:
      "Concurrent edits from different operators must not silently overwrite each other.",
    validation:
      "Maintain a version or update timestamp and surface the conflict before finalizing the answer.",
    severity: "critical",
  },
  {
    id: "Q16",
    section: "B2",
    title: "Group decision support",
    requirement:
      "If the prompt involves multiple stakeholders, summarize the consensus and outstanding objections.",
    validation:
      "Flag divergent positions and the evidence behind each recommendation.",
    severity: "medium",
  },
  {
    id: "Q17",
    section: "B2",
    title: "Safety escalation prioritization",
    requirement:
      "Critical safety risks must be prioritized above routine operational summaries.",
    validation:
      "Escalate HSE and response actions before low-risk optimization recommendations.",
    severity: "critical",
  },
  {
    id: "Q18",
    section: "B2",
    title: "Final answer integrity",
    requirement:
      "The final response must be concise, evidence-based, and consistent with the chosen visual format and all active constraints.",
    validation:
      "Ensure the final output does not contradict any prior thread fact or user override.",
    severity: "high",
  },
];

const alertDefinitions = [
  {
    id: "ALERT-FACT-MISMATCH",
    severity: "critical",
    title: "Fact mismatch detected",
    trigger:
      "Value or date differs from the ground-truth record or field date.",
    action:
      "Block the answer and request a re-query of the underlying asset record.",
  },
  {
    id: "ALERT-EVIDENCE-MISSING",
    severity: "high",
    title: "Evidence citation missing",
    trigger:
      "A conclusion is made without a source note, inspection record, or SOP reference.",
    action:
      "Attach the source reference and mark the claim as unverified until linked.",
  },
  {
    id: "ALERT-UI-RENDER",
    severity: "medium",
    title: "Visual selection mismatch",
    trigger:
      "The user requested a visual but the assistant returned an unsupported text-only result.",
    action:
      "Render the correct chart, table, map, or status summary inline in the chat message.",
  },
  {
    id: "ALERT-PRIVACY",
    severity: "critical",
    title: "Restricted data risk",
    trigger:
      "A protected HSE note or personal context appears in a non-authorized thread.",
    action:
      "Mask the content and require access verification before response is delivered.",
  },
  {
    id: "ALERT-CONFLICT",
    severity: "high",
    title: "Operator override conflict",
    trigger:
      "A user correction conflicts with current telemetry or a rule-based threshold.",
    action:
      "Present the contradiction, keep the override flagged, and recommend verification.",
  },
  {
    id: "ALERT-SAFETY",
    severity: "critical",
    title: "Safety escalation required",
    trigger:
      "Critical threshold or active spill or thermal anomaly crosses a safety trigger.",
    action:
      "Raise the issue above normal operations and require a field response path.",
  },
];

const alertHeatmapMonths = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const alertHeatmapCells = Array.from({ length: 53 }, (_, weekIndex) =>
  Array.from({ length: 7 }, (_, dayIndex) => {
    const generatedValue = (weekIndex * 3 + dayIndex * 5 + (weekIndex % 4)) % 5;

    return {
      id: `alert-cell-${weekIndex}-${dayIndex}`,
      value: generatedValue,
      dayIndex,
      weekIndex,
    };
  }),
);

const backendFeatureCards = [
  {
    title: "Raw data + derived views",
    value: "wells • inspections • repairs • regulatory_events • notes",
    tone: "cyan",
    icon: <Database size={16} />,
  },
  {
    title: "Deterministic tools",
    value: "well_status • downtime • spills • compliance • repairs",
    tone: "emerald",
    icon: <Gauge size={16} />,
  },
  {
    title: "Private memory",
    value: "user-scoped recall + note + correction pipeline",
    tone: "amber",
    icon: <ShieldCheck size={16} />,
  },
  {
    title: "Visual response contract",
    value: "{ rows, evidence, visual, window }",
    tone: "rose",
    icon: <FileText size={16} />,
  },
];

const baseThreads = [
  {
    id: "thread-1",
    title: "Production swing in SW-23",
    messages: [
      {
        role: "user",
        text: "Summarize all non-producing wells in SW-23 and identify the likely causes from the sensor and inspection history.",
      },
      {
        role: "assistant",
        text: "I found three wells trending into non-producing status. T350 and A-17 are the highest risk clusters, with thermal drift and pressure instability dominating the likely root cause set.",
        citations: ["[INS-WELL-0001-14]", "[SR-02]", "[T200 Manual]"],
        statuses: [
          {
            icon: <Zap size={12} />,
            label: "Querying SQL database for 2026 downtime records...",
          },
          {
            icon: <Search size={12} />,
            label: "Searching vector DB for SR-02 containment rules...",
          },
          {
            icon: <Gauge size={12} />,
            label: "Analyzing temperature delta across 200 wells...",
          },
        ],
      },
    ],
  },
  {
    id: "thread-2",
    title: "Spill risk brief",
    messages: [
      {
        role: "user",
        text: "Are there any spill-prone areas or unresolved containment actions in the last 24 hours?",
      },
      {
        role: "assistant",
        text: "Two sites are still pending containment review. NW-12 remains the highest priority due to delayed emergency skid inspection and a recent pressure excursion.",
        citations: ["[SR-02]"],
        statuses: [
          {
            icon: <Zap size={12} />,
            label: "Cross-checking spill triage ledger...",
          },
          {
            icon: <Search size={12} />,
            label: "Validating the last 24h containment actions...",
          },
        ],
      },
    ],
  },
  {
    id: "thread-3",
    title: "HSE compliance walk-through",
    messages: [
      {
        role: "user",
        text: "Give me the HSE posture for the current field shift and flag any unresolved safety actions.",
      },
      {
        role: "assistant",
        text: "HSE compliance remains above threshold at 96.4%. The main unresolved action is emergency skid inspection at NW-12, which is still open in the safety review.",
        citations: ["[SR-02]"],
        statuses: [
          {
            icon: <ShieldCheck size={12} />,
            label: "Checking shift compliance indicators...",
          },
          {
            icon: <Search size={12} />,
            label: "Reviewing emergency response logs...",
          },
        ],
      },
    ],
  },
];

function App() {
  const [threads, setThreads] = useState(baseThreads);
  const [activeThreadId, setActiveThreadId] = useState(baseThreads[0].id);
  const [persona, setPersona] = useState(personaOptions[0]);
  const [area, setArea] = useState(areaOptions[0]);
  const [input, setInput] = useState("");
  const [contextOpen, setContextOpen] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
  const [studioMode, setStudioMode] = useState("overview");
  const [activeNav, setActiveNav] = useState("home");
  const [backendHealth, setBackendHealth] = useState({
    status: "initializing",
    version: "v0.5.0",
  });

  useEffect(() => {
    let isMounted = true;

    backendApi.getHealth().then((response) => {
      if (!isMounted || !response.ok) return;
      setBackendHealth(response.data);
    });

    return () => {
      isMounted = false;
    };
  }, []);

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? threads[0],
    [threads, activeThreadId],
  );

  const logEntries = [
    {
      time: "09:22",
      type: "Warning",
      title: "T350 thermal drift above threshold",
      detail:
        "SW-23 • Pressure and thermal deviation persisted for 12 minutes.",
    },
    {
      time: "11:48",
      type: "Info",
      title: "Inspection window opened",
      detail:
        "Field inspector reviewed route NE-08 and logged operational notes.",
    },
    {
      time: "13:17",
      type: "Critical",
      title: "HSE containment review triggered",
      detail: "NW-12 skid check escalated after a delayed maintenance action.",
    },
    {
      time: "15:40",
      type: "Resolved",
      title: "Spill checklist closed",
      detail: "SE-04 containment check passed and report archived.",
    },
  ];

  const addThread = () => {
    const id = `thread-${Date.now()}`;
    const nextThread = {
      id,
      title: `New thread ${threads.length + 1}`,
      messages: [
        {
          role: "assistant",
          text: "Ready to help with the next operational query. Add a field signal, asset, or report and I will synthesize the likely root cause and next action.",
          citations: ["[SR-02]"],
          statuses: [
            {
              icon: <Sparkles size={12} />,
              label: "Standby, ready for a new operational request...",
            },
          ],
        },
      ],
    };

    setThreads((prev) => [nextThread, ...prev]);
    setActiveThreadId(id);
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!input.trim()) return;

    const userMessage = {
      role: "user",
      text: input.trim(),
    };

    const assistantMessage = {
      role: "assistant",
      text: "I checked the latest telemetry, inspection notes, and containment review in the current area. The highest impact issue remains T350 in SW-23 with thermal drift, pressure deviation, and delayed maintenance follow-through.",
      citations: ["[INS-WELL-0001-14]", "[SR-02]", "[T200 Manual]"],
      statuses: [
        {
          icon: <Zap size={12} />,
          label: "Querying SQL database for the latest downtime records...",
        },
        {
          icon: <Search size={12} />,
          label:
            "Searching the vector index for the relevant SOPs and prior inspections...",
        },
        {
          icon: <Gauge size={12} />,
          label: "Comparing thermal deltas across the current field cluster...",
        },
      ],
    };

    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === activeThreadId
          ? {
              ...thread,
              title: input.trim().slice(0, 28) || thread.title,
              messages: [...thread.messages, userMessage, assistantMessage],
            }
          : thread,
      ),
    );

    setInput("");
    setContextOpen(false);
    setSlashOpen(false);
  };

  return (
    <div className='app-shell'>
      <header className='topbar'>
        <div className='brand-wrap'>
          <div className='brand-mark'>
            <span className='brand-dot' />
          </div>
          <div className='brand-copy'>
            <div className='brand-title'>
              FlytBase Asset Intelligence Copilot
            </div>
          </div>
        </div>

        <div className='toolbar'>
          <div className='field-date-badge'>
            <CalendarRange size={14} />
            <span>Field Date: {currentFieldDate}</span>
          </div>

          <label className='select-group'>
            <span>Persona</span>
            <div className='select-field'>
              <select
                value={persona}
                onChange={(event) => setPersona(event.target.value)}>
                {personaOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </div>
          </label>

          <label className='select-group'>
            <span>Area</span>
            <div className='select-field'>
              <select
                value={area}
                onChange={(event) => setArea(event.target.value)}>
                {areaOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
        </div>
      </header>

      {activeNav === "home" && (
        <div className='workspace-layout'>
          <aside className='sidebar-panel'>
            <div className='panel-header'>
              <div>
                <p className='eyebrow'>Context</p>
                <h3>Recent threads</h3>
              </div>
              <button type='button' className='mini-action' onClick={addThread}>
                <Plus size={12} />
                <span>New</span>
              </button>
            </div>

            <div className='thread-list'>
              {threads.map((thread) => (
                <button
                  key={thread.id}
                  type='button'
                  className={`thread-item ${thread.id === activeThreadId ? "active" : ""}`}
                  onClick={() => setActiveThreadId(thread.id)}>
                  <Circle size={8} className='thread-dot' />
                  <span>{thread.title}</span>
                </button>
              ))}
            </div>

            <div className='quick-actions'>
              <p className='eyebrow'>Quick queries</p>
              <div className='pill-list'>
                {quickActions.map((item) => (
                  <button key={item} type='button' className='quick-pill'>
                    {item}
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <main className='chat-workspace'>
            <section className='chat-main'>
              <div className='summary-grid'>
                <SummaryCard
                  icon={<Gauge size={16} />}
                  label='Active wells'
                  value='184'
                  delta='12 above avg'
                  tone='cyan'
                />
                <SummaryCard
                  icon={<Thermometer size={16} />}
                  label='Thermal risk'
                  value='14%'
                  delta='+3.1%'
                  tone='amber'
                />
                <SummaryCard
                  icon={<ShieldCheck size={16} />}
                  label='HSE compliance'
                  value='96.4%'
                  delta='Stable'
                  tone='emerald'
                />
                <SummaryCard
                  icon={<FileText size={16} />}
                  label='Open reports'
                  value='09'
                  delta='2 due today'
                  tone='rose'
                />
              </div>

              <div className='chat-feed' aria-label='Chat feed'>
                {activeThread.messages.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`message-row ${message.role === "assistant" ? "assistant" : "user"}`}>
                    <div className='message-avatar'>
                      {message.role === "assistant" ? (
                        <Bot size={15} />
                      ) : (
                        <span>U</span>
                      )}
                    </div>

                    <div className='message-bubble'>
                      <div className='message-body'>
                        <p>{message.text}</p>

                        {message.statuses && (
                          <div className='execution-stack'>
                            {message.statuses.map((status, statusIndex) => (
                              <div
                                key={`${status.label}-${statusIndex}`}
                                className='status-badge'>
                                <span className='status-icon'>
                                  {status.icon}
                                </span>
                                <span>{status.label}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {message.citations && (
                          <div className='evidence-row'>
                            {message.citations.map((item) => (
                              <span
                                key={item}
                                className='citation-badge'
                                tabIndex={0}>
                                {item}
                                <span
                                  className='citation-popover'
                                  role='tooltip'>
                                  <strong>{item}</strong>
                                  <p>
                                    {
                                      evidenceLinks.find(
                                        (source) => source.id === item,
                                      )?.snippet
                                    }
                                  </p>
                                  <small>
                                    {
                                      evidenceLinks.find(
                                        (source) => source.id === item,
                                      )?.source
                                    }
                                  </small>
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      {message.role === "assistant" && (
                        <div className='message-actions'>
                          <button type='button'>
                            <Copy size={12} />
                            Copy
                          </button>
                          <button type='button'>
                            <MessageSquareQuote size={12} />
                            Regenerate
                          </button>
                          <button type='button'>
                            <Sparkles size={12} />
                            Open in Studio
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <form className='composer' onSubmit={handleSubmit}>
                <div className='composer-topline'>
                  <button
                    type='button'
                    className='composer-chip'
                    onClick={() => setContextOpen((prev) => !prev)}>
                    <Search size={12} />@ Context
                  </button>
                  <button
                    type='button'
                    className='composer-chip'
                    onClick={() => setSlashOpen((prev) => !prev)}>
                    <Sparkles size={12} />/ Command
                  </button>
                </div>

                {contextOpen && (
                  <div className='menu-popover mention-popover'>
                    {mentionOptions.map((option) => (
                      <button
                        key={option}
                        type='button'
                        onClick={() =>
                          setInput(
                            (prev) => `${prev}${prev ? " " : ""}${option}`,
                          )
                        }>
                        {option}
                      </button>
                    ))}
                  </div>
                )}

                {slashOpen && (
                  <div className='menu-popover slash-popover'>
                    {slashCommands.map((command) => (
                      <button
                        key={command}
                        type='button'
                        onClick={() => setInput(command)}>
                        {command}
                      </button>
                    ))}
                  </div>
                )}

                <div className='input-row'>
                  <button
                    type='button'
                    className='composer-icon'
                    aria-label='Attach image'>
                    <ImagePlus size={16} />
                  </button>
                  <button
                    type='button'
                    className='composer-icon'
                    aria-label='Attach file'>
                    <Paperclip size={16} />
                  </button>
                  <textarea
                    rows={1}
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    placeholder='Ask the copilot about wells, alarms, spills, HSE, or reports...'
                  />
                  <button
                    type='button'
                    className='composer-icon'
                    aria-label='Voice input'>
                    <Mic size={16} />
                  </button>
                  <button
                    type='submit'
                    className='send-button'
                    aria-label='Send prompt'>
                    <ArrowUpRight size={16} />
                  </button>
                </div>
              </form>
            </section>

            <aside className='studio-panel'>
              <div className='studio-header'>
                <div>
                  <p className='eyebrow'>Studio</p>
                  <h3>Asset intelligence</h3>
                </div>
                <div className='studio-actions'>
                  <button type='button'>CSV</button>
                  <button type='button'>JSON</button>
                </div>
              </div>

              <div className='studio-tabs'>
                <button
                  type='button'
                  className={studioMode === "overview" ? "active" : ""}
                  onClick={() => setStudioMode("overview")}>
                  Overview
                </button>
                <button
                  type='button'
                  className={studioMode === "charts" ? "active" : ""}
                  onClick={() => setStudioMode("charts")}>
                  Charts
                </button>
              </div>

              <div className='artifact-card'>
                <div className='artifact-head'>
                  <span className='status-dot success' />
                  <span>Active operational summary</span>
                </div>

                {studioMode === "overview" && (
                  <>
                    <div className='artifact-metrics'>
                      <div>
                        <small>Non-producing</small>
                        <strong>03</strong>
                      </div>
                      <div>
                        <small>Critical heat</small>
                        <strong>02</strong>
                      </div>
                      <div>
                        <small>HSE actions</small>
                        <strong>07</strong>
                      </div>
                    </div>

                    <div className='table-shell'>
                      <table>
                        <thead>
                          <tr>
                            <th>Well</th>
                            <th>Status</th>
                            <th>Temp</th>
                            <th>Pressure</th>
                          </tr>
                        </thead>
                        <tbody>
                          {tableRows.map((row) => (
                            <tr key={row.well}>
                              <td>{row.well}</td>
                              <td>
                                <span
                                  className={`table-tag ${row.status.toLowerCase().replace(/\s+/g, "-")}`}>
                                  {row.status}
                                </span>
                              </td>
                              <td>{row.temp}</td>
                              <td>{row.pressure}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}

                {studioMode === "charts" && (
                  <div className='chart-layout'>
                    <div className='mini-chart'>
                      <ResponsiveContainer width='100%' height={160}>
                        <BarChart data={chartSeries}>
                          <CartesianGrid
                            stroke='rgba(148,163,184,0.1)'
                            vertical={false}
                          />
                          <XAxis
                            dataKey='name'
                            tick={{ fill: "#94A3B8", fontSize: 10 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <YAxis
                            tick={{ fill: "#94A3B8", fontSize: 10 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "#0f172a",
                              border: "1px solid rgba(148,163,184,0.2)",
                              borderRadius: "10px",
                              color: "#E2E8F0",
                            }}
                          />
                          <Bar
                            dataKey='value'
                            radius={[6, 6, 0, 0]}
                            fill='#0EA5E9'
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                    <div className='mini-chart'>
                      <ResponsiveContainer width='100%' height={160}>
                        <AreaChart data={tempSeries}>
                          <defs>
                            <linearGradient
                              id='studioFill'
                              x1='0'
                              x2='0'
                              y1='0'
                              y2='1'>
                              <stop
                                offset='5%'
                                stopColor='#10B981'
                                stopOpacity={0.55}
                              />
                              <stop
                                offset='95%'
                                stopColor='#10B981'
                                stopOpacity={0.05}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            stroke='rgba(148,163,184,0.1)'
                            vertical={false}
                          />
                          <XAxis
                            dataKey='time'
                            tick={{ fill: "#94A3B8", fontSize: 10 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <YAxis
                            tick={{ fill: "#94A3B8", fontSize: 10 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "#0f172a",
                              border: "1px solid rgba(148,163,184,0.2)",
                              borderRadius: "10px",
                              color: "#E2E8F0",
                            }}
                          />
                          <Area
                            type='monotone'
                            dataKey='temp'
                            stroke='#10B981'
                            strokeWidth={2}
                            fill='url(#studioFill)'
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>

                    <div className='map-card'>
                      <div className='map-surface'>
                        <div className='map-pin pin-a'>
                          <MapPinned size={12} />
                        </div>
                        <div className='map-pin pin-b'>
                          <MapPinned size={12} />
                        </div>
                        <div className='map-pin pin-c'>
                          <MapPinned size={12} />
                        </div>
                      </div>
                      <div className='map-legend'>
                        <span>
                          <i className='legend-cyan' /> SW-23
                        </span>
                        <span>
                          <i className='legend-amber' /> NW-12
                        </span>
                        <span>
                          <i className='legend-rose' /> SE-04
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className='rulebook-block'>
                <div className='rulebook-head'>
                  <p className='eyebrow'>Rulebook</p>
                  <h4>Benchmark guardrails Q1–Q18</h4>
                </div>

                <div className='rulebook-list'>
                  {benchmarkRules.map((rule) => (
                    <div key={rule.id} className='rule-card'>
                      <div className='rule-card-head'>
                        <span className={`severity-badge ${rule.severity}`}>
                          {rule.id}
                        </span>
                        <span>{rule.section}</span>
                      </div>
                      <strong>{rule.title}</strong>
                      <p>{rule.requirement}</p>
                      <small>{rule.validation}</small>
                    </div>
                  ))}
                </div>
              </div>

              <div className='alert-block'>
                <div className='rulebook-head'>
                  <p className='eyebrow'>Alerts</p>
                  <h4>Operational guardrail triggers</h4>
                </div>

                <div className='alert-heatmap-card'>
                  <div className='alert-heatmap-title'>
                    1,234 contributions in the last year
                  </div>

                  <div className='alert-heatmap-shell'>
                    <div className='heatmap-weekday-column'>
                      <span>Mon</span>
                      <span>Wed</span>
                      <span>Fri</span>
                    </div>

                    <div className='heatmap-matrix'>
                      <div className='heatmap-month-row'>
                        {alertHeatmapMonths.map((month) => (
                          <span key={month}>{month}</span>
                        ))}
                      </div>

                      <div className='heatmap-grid'>
                        {alertHeatmapCells.flatMap((week, weekIndex) =>
                          week.map((cell, dayIndex) => (
                            <span
                              key={cell.id}
                              className={`heatmap-cell level-${cell.value}`}
                              style={{
                                gridColumn: weekIndex + 1,
                                gridRow: dayIndex + 1,
                              }}
                              aria-label={`Alert level ${cell.value}`}
                              title={`Week ${weekIndex + 1}, day ${dayIndex + 1}: ${cell.value} alerts`}
                            />
                          )),
                        )}
                      </div>
                    </div>
                  </div>

                  <div className='heatmap-legend'>
                    <span>Less</span>
                    <div className='legend-scale'>
                      {[0, 1, 2, 3, 4].map((level) => (
                        <span
                          key={level}
                          className={`legend-pill level-${level}`}
                        />
                      ))}
                    </div>
                    <span>More</span>
                  </div>
                </div>

                <div className='alert-list'>
                  {alertDefinitions.map((alert) => (
                    <div key={alert.id} className='alert-item'>
                      <div className='rule-card-head'>
                        <span className={`severity-badge ${alert.severity}`}>
                          {alert.id}
                        </span>
                        <span>{alert.severity}</span>
                      </div>
                      <strong>{alert.title}</strong>
                      <p>{alert.trigger}</p>
                      <small>{alert.action}</small>
                    </div>
                  ))}
                </div>
              </div>

              <div className='backend-block'>
                <div className='rulebook-head'>
                  <p className='eyebrow'>Backend-ready</p>
                  <h4>API contract and system model</h4>
                </div>

                <div className='backend-status'>
                  <span className='status-pill'>{backendHealth.status}</span>
                  <span>{backendHealth.version}</span>
                  <span>{backendHealth.engine}</span>
                </div>

                <div className='backend-feature-grid'>
                  {backendFeatureCards.map((item) => (
                    <div
                      key={item.title}
                      className={`backend-card ${item.tone}`}>
                      <div className='backend-icon'>{item.icon}</div>
                      <div>
                        <strong>{item.title}</strong>
                        <small>{item.value}</small>
                      </div>
                    </div>
                  ))}
                </div>

                <div className='contract-list'>
                  {backendContracts.map((contract) => (
                    <div key={contract.name} className='contract-row'>
                      <div className='contract-head'>
                        <span>{contract.name}</span>
                        <span className='method-pill'>{contract.method}</span>
                      </div>
                      <small>{contract.route}</small>
                      <p>{contract.purpose}</p>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </main>
        </div>
      )}

      {activeNav === "dashboard" && (
        <div className='section-shell dashboard-shell'>
          <div className='section-header'>
            <div>
              <p className='eyebrow'>Dashboard</p>
              <h3>Operations overview</h3>
            </div>
          </div>

          <div className='summary-grid'>
            <SummaryCard
              icon={<Gauge size={16} />}
              label='Active wells'
              value='184'
              delta='12 above avg'
              tone='cyan'
            />
            <SummaryCard
              icon={<Thermometer size={16} />}
              label='Thermal risk'
              value='14%'
              delta='+3.1%'
              tone='amber'
            />
            <SummaryCard
              icon={<ShieldCheck size={16} />}
              label='HSE compliance'
              value='96.4%'
              delta='Stable'
              tone='emerald'
            />
            <SummaryCard
              icon={<FileText size={16} />}
              label='Open reports'
              value='09'
              delta='2 due today'
              tone='rose'
            />
          </div>

          <div className='dashboard-grid'>
            <div className='mini-chart large'>
              <ResponsiveContainer width='100%' height={220}>
                <BarChart data={chartSeries}>
                  <CartesianGrid
                    stroke='rgba(148,163,184,0.1)'
                    vertical={false}
                  />
                  <XAxis
                    dataKey='name'
                    tick={{ fill: "#94A3B8", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "#94A3B8", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      border: "1px solid rgba(148,163,184,0.2)",
                      borderRadius: "10px",
                      color: "#E2E8F0",
                    }}
                  />
                  <Bar dataKey='value' radius={[6, 6, 0, 0]} fill='#0EA5E9' />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className='mini-chart large'>
              <ResponsiveContainer width='100%' height={220}>
                <AreaChart data={tempSeries}>
                  <defs>
                    <linearGradient
                      id='dashboardFill'
                      x1='0'
                      x2='0'
                      y1='0'
                      y2='1'>
                      <stop
                        offset='5%'
                        stopColor='#10B981'
                        stopOpacity={0.55}
                      />
                      <stop
                        offset='95%'
                        stopColor='#10B981'
                        stopOpacity={0.05}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke='rgba(148,163,184,0.1)'
                    vertical={false}
                  />
                  <XAxis
                    dataKey='time'
                    tick={{ fill: "#94A3B8", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "#94A3B8", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#0f172a",
                      border: "1px solid rgba(148,163,184,0.2)",
                      borderRadius: "10px",
                      color: "#E2E8F0",
                    }}
                  />
                  <Area
                    type='monotone'
                    dataKey='temp'
                    stroke='#10B981'
                    strokeWidth={2}
                    fill='url(#dashboardFill)'
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className='map-card dashboard-map'>
            <div className='map-surface'>
              <div className='map-pin pin-a'>
                <MapPinned size={12} />
              </div>
              <div className='map-pin pin-b'>
                <MapPinned size={12} />
              </div>
              <div className='map-pin pin-c'>
                <MapPinned size={12} />
              </div>
            </div>
            <div className='map-legend'>
              <span>
                <i className='legend-cyan' /> SW-23
              </span>
              <span>
                <i className='legend-amber' /> NW-12
              </span>
              <span>
                <i className='legend-rose' /> SE-04
              </span>
            </div>
          </div>
        </div>
      )}

      {activeNav === "logs" && (
        <div className='section-shell logs-shell'>
          <div className='section-header'>
            <div>
              <p className='eyebrow'>Logs</p>
              <h3>Operational event stream</h3>
            </div>
          </div>

          <div className='logs-list'>
            {logEntries.map((entry) => (
              <div key={`${entry.time}-${entry.title}`} className='log-item'>
                <div className='log-time'>{entry.time}</div>
                <div className='log-content'>
                  <span className={`log-type ${entry.type.toLowerCase()}`}>
                    {entry.type}
                  </span>
                  <strong>{entry.title}</strong>
                  <p>{entry.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <nav className='bottom-nav' aria-label='Main navigation'>
        <button
          type='button'
          className={`nav-item ${activeNav === "home" ? "active" : ""}`}
          onClick={() => setActiveNav("home")}>
          <Home size={17} />
          <span>Home</span>
        </button>
        <button
          type='button'
          className={`nav-item ${activeNav === "dashboard" ? "active" : ""}`}
          onClick={() => setActiveNav("dashboard")}>
          <LayoutGrid size={17} />
          <span>Dashboard</span>
        </button>
        <button
          type='button'
          className={`nav-item ${activeNav === "logs" ? "active" : ""}`}
          onClick={() => setActiveNav("logs")}>
          <FileText size={17} />
          <span>Logs</span>
        </button>
      </nav>

      <button
        type='button'
        className='floating-fab'
        aria-label='Open AI assistant'>
        <Bot size={18} />
      </button>
    </div>
  );
}

function SummaryCard({ icon, label, value, delta, tone }) {
  return (
    <div className={`summary-card ${tone}`}>
      <div className='summary-icon'>{icon}</div>
      <div className='summary-copy'>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{delta}</small>
      </div>
    </div>
  );
}

export default App;
