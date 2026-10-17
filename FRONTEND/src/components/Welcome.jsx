import { Activity, Droplets, ShieldAlert, TrendingDown } from "lucide-react";

const SUGGESTIONS = [
  {
    icon: Activity,
    title: "Is a well producing?",
    question: "Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card.",
  },
  {
    icon: TrendingDown,
    title: "Biggest downtime",
    question: "Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart.",
  },
  {
    icon: Droplets,
    title: "Spills by area and month",
    question: "Show a heatmap of 2026 spills by geographic area and month.",
  },
  {
    icon: ShieldAlert,
    title: "Rules a well has broken",
    question: "Which rules has WELL-0001 broken in the last 12 months, and what is still open?",
  },
];

export default function Welcome({ name, onPick, disabled }) {
  return (
    <div className='welcome'>
      <h1>{name ? `Hello, ${name.split(" ")[0]}` : "Hello"}</h1>
      <p>What would you like to know about the oil field?</p>
      <div className='suggestions'>
        {SUGGESTIONS.map(({ icon: Icon, title, question }) => (
          <button key={title} type='button' disabled={disabled} onClick={() => onPick(question)}>
            <Icon size={18} />
            <strong>{title}</strong>
            <span>{question}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
