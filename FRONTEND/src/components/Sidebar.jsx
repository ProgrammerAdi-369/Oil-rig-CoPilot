import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, MessageSquarePlus, Trash2 } from "lucide-react";

const initials = (name = "") =>
  name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2);

function UserMenu({ users, user, onSelectUser, yesterday, onYesterday }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => !ref.current?.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className='user-menu' ref={ref}>
      {open && (
        <div className='user-popover' role='menu'>
          <p className='user-popover-title'>Signed in as</p>
          <div className='user-list'>
            {users.map((u) => (
              <button
                key={u.user_id}
                type='button'
                role='menuitemradio'
                aria-checked={u.user_id === user?.user_id}
                onClick={() => {
                  onSelectUser(u.user_id);
                  setOpen(false);
                }}>
                <span className='avatar small'>{initials(u.name)}</span>
                <span className='user-line'>
                  <strong>{u.name}</strong>
                  <small>{u.role.replaceAll("_", " ")}</small>
                </span>
                {u.user_id === user?.user_id && <Check size={14} />}
              </button>
            ))}
          </div>
          <label className='yesterday-toggle' title='Sends the next messages as if they were written the day before, so "the wells we discussed yesterday" can be tested'>
            <input type='checkbox' checked={yesterday} onChange={(e) => onYesterday(e.target.checked)} />
            <span>Simulate yesterday</span>
          </label>
        </div>
      )}
      <button type='button' className='user-button' onClick={() => setOpen((o) => !o)} aria-haspopup='menu' aria-expanded={open}>
        <span className='avatar'>{initials(user?.name ?? "U")}</span>
        <span className='user-line'>
          <strong>{user?.name ?? "Loading…"}</strong>
          <small>{user ? user.role.replaceAll("_", " ") : ""}</small>
        </span>
        <ChevronsUpDown size={14} />
      </button>
    </div>
  );
}

export default function Sidebar({ open, threads, activeId, onNew, onOpen, onDelete, ...userProps }) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className='sidebar-top'>
        <div className='brand'>
          <span className='brand-dot' />
          <span>Asset Copilot</span>
        </div>
        <button type='button' className='new-chat' onClick={onNew}>
          <MessageSquarePlus size={16} />
          New chat
        </button>
      </div>

      <nav className='history' aria-label='Chat history'>
        {threads.length === 0 && <p className='history-empty'>Your conversations will appear here.</p>}
        {threads.map((t) => (
          <div key={t.chat_id} className={`history-item ${t.chat_id === activeId ? "active" : ""}`}>
            <button type='button' className='history-open' onClick={() => onOpen(t.chat_id)} title={t.title}>
              {(t.title ?? "Conversation").slice(0, 60)}
            </button>
            <button type='button' className='history-delete' aria-label='Delete chat' onClick={() => onDelete(t.chat_id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </nav>

      <UserMenu {...userProps} />
    </aside>
  );
}
