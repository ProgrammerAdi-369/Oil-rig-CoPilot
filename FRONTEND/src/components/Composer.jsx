import { useLayoutEffect, useRef } from "react";
import { ArrowUp } from "lucide-react";

export default function Composer({ value, onChange, onSend, busy }) {
  const ref = useRef(null);

  // grow with the text up to a limit, like ChatGPT / Claude
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <form
      className='composer'
      onSubmit={(e) => {
        e.preventDefault();
        onSend();
      }}>
      <div className='composer-box'>
        <textarea
          ref={ref}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
          placeholder='Ask about wells, spills, downtime, SOP breaches or repairs…'
          aria-label='Message'
        />
        <button type='submit' className='send' aria-label='Send message' disabled={busy || !value.trim()}>
          <ArrowUp size={18} />
        </button>
      </div>
      <p className='composer-hint'>Answers are generated from the field database and cite their records. Check the sources before acting.</p>
    </form>
  );
}
