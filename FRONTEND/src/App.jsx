import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Menu } from "lucide-react";
import { api } from "./services/assetApi";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import Welcome from "./components/Welcome";
import ChatMessage from "./components/ChatMessage";
import ErrorBoundary from "./components/ErrorBoundary";
import "./chat.css";
import "./visuals.css";

const DEFAULT_USER = "U-201"; // Michael Turner, the production supervisor the benchmark questions use

const shiftDay = (iso, days) => new Date(Date.parse(`${iso}T00:00:00Z`) + days * 864e5).toISOString().slice(0, 10);

export default function App() {
  const [meta, setMeta] = useState(null);
  const [users, setUsers] = useState([]);
  const [bootError, setBootError] = useState(null);
  const [bootTry, setBootTry] = useState(0);
  const [userId, setUserId] = useState(() => localStorage.getItem("copilot-user") || DEFAULT_USER);
  const [yesterday, setYesterday] = useState(false);

  const [threads, setThreads] = useState([]);
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [version, setVersion] = useState(0); // bumped after each answer to refresh the history list

  const userRef = useRef(userId);
  const feedRef = useRef(null);

  const user = useMemo(() => users.find((u) => u.user_id === userId) ?? null, [users, userId]);

  // ---- boot: users and data date; keeps retrying while the backend is down or still starting
  useEffect(() => {
    let timer;
    Promise.all([api.meta(), api.users()])
      .then(([m, u]) => {
        setMeta(m);
        setUsers(u);
        setBootError(null);
      })
      .catch((e) => {
        setBootError(e.message);
        timer = setTimeout(() => setBootTry((n) => n + 1), 3000);
      });
    return () => clearTimeout(timer);
  }, [bootTry]);

  // ---- this user's chat history (private: the server filters by the X-User-Id header)
  useEffect(() => {
    let live = true;
    api
      .chats(userId)
      .then((list) => live && setThreads(list))
      .catch(() => {}); // offline: the banner already says so
    return () => {
      live = false;
    };
  }, [userId, version]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const selectUser = (uid) => {
    userRef.current = uid; // late replies for the previous user are ignored
    localStorage.setItem("copilot-user", uid);
    setChatId(null);
    setMessages([]);
    setThreads([]);
    setUserId(uid);
  };

  const fieldDay = meta ? shiftDay(meta.as_of, yesterday ? -1 : 0) : undefined;

  const send = useCallback(
    async (text) => {
      const message = text.trim();
      if (!message || busy) return;
      const uid = userId;
      setBusy(true);
      setInput("");
      setMessages((m) => [...m.filter((x) => !x.error), { role: "user", text: message }, { role: "assistant", pending: true }]);
      try {
        const out = await api.send(uid, chatId, message, fieldDay);
        if (userRef.current !== uid) return;
        setChatId(out.chat_id);
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", text: out.text, payload: out }]);
        setVersion((v) => v + 1);
      } catch (err) {
        if (userRef.current !== uid) return;
        setMessages((m) => [...m.slice(0, -1), { role: "assistant", error: err.message, retry: message }]);
      } finally {
        setBusy(false);
      }
    },
    [busy, userId, chatId, fieldDay],
  );

  const openThread = async (id) => {
    const uid = userId;
    setSidebarOpen(false);
    setChatId(id);
    setMessages([]);
    try {
      const out = await api.chat(uid, id);
      if (userRef.current === uid) setMessages(out.messages.map((m) => ({ role: m.role, text: m.text, payload: m.payload })));
    } catch (err) {
      setMessages([{ role: "assistant", error: err.message }]);
    }
  };

  const newChat = () => {
    setSidebarOpen(false);
    setChatId(null);
    setMessages([]);
  };

  const deleteThread = async (id) => {
    try {
      await api.deleteChat(userId, id);
      setThreads((t) => t.filter((x) => x.chat_id !== id));
      if (id === chatId) newChat();
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", error: err.message }]);
    }
  };

  const regenerate = (index) => {
    const question = [...messages.slice(0, index)].reverse().find((m) => m.role === "user")?.text;
    if (question) send(question);
  };

  return (
    <div className='app'>
      <Sidebar
        open={sidebarOpen}
        threads={threads}
        activeId={chatId}
        onNew={newChat}
        onOpen={openThread}
        onDelete={deleteThread}
        users={users}
        user={user}
        onSelectUser={selectUser}
        yesterday={yesterday}
        onYesterday={setYesterday}
      />
      {sidebarOpen && <button type='button' className='scrim' aria-label='Close menu' onClick={() => setSidebarOpen(false)} />}

      <main className='main'>
        <header className='mobile-bar'>
          <button type='button' aria-label='Open menu' onClick={() => setSidebarOpen(true)}>
            <Menu size={20} />
          </button>
          <span>Asset Copilot</span>
        </header>

        {bootError && (
          <div className='banner error'>
            <strong>Backend not reachable.</strong> {bootError}
          </div>
        )}
        {meta && !meta.llm_ready && <div className='banner'>No language-model key is configured on the server (GEMINI_API_KEY), so chat is unavailable.</div>}
        {yesterday && meta && <div className='banner info'>Simulating {shiftDay(meta.as_of, -1)}: new messages are stored as written yesterday.</div>}

        <div className='feed' ref={feedRef}>
          <div className='column'>
            {messages.length === 0 ? (
              <Welcome name={user?.name} onPick={send} disabled={busy || !!bootError} />
            ) : (
              messages.map((message, index) => (
                <ErrorBoundary key={`${message.role}-${index}`}>
                  <ChatMessage message={message} onRegenerate={() => regenerate(index)} onRetry={send} />
                </ErrorBoundary>
              ))
            )}
          </div>
        </div>

        <div className='column composer-wrap'>
          <Composer value={input} onChange={setInput} onSend={() => send(input)} busy={busy} />
        </div>
      </main>
    </div>
  );
}
