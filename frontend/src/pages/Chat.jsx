import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import { useSocket } from "../useSocket.js";

function titleFor(conv, meId) {
  if (conv.type === "group") return conv.name || "Group";
  const other = conv.members.find((m) => m.id !== meId);
  return other?.username || "Direct";
}

function initials(name) {
  return (name || "?").slice(0, 2).toUpperCase();
}

function timeLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Avatar({ src, name, className = "" }) {
  if (src) return <img className={`avatar ${className}`} src={src} alt={name || ""} />;
  return <span className={`avatar ${className}`}>{initials(name)}</span>;
}

function convoPhoto(conv, meId) {
  if (conv.type === "group") return conv.avatar_url || null;
  return conv.members.find((m) => m.id !== meId)?.avatar_url || null;
}

export default function Chat() {
  const { user, token, logout, updateUser } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState([]);
  const [searchEmpty, setSearchEmpty] = useState("");
  const [typing, setTyping] = useState({});
  const [presence, setPresence] = useState({});
  const [notifications, setNotifications] = useState([]);
  const [groupOpen, setGroupOpen] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [groupPicked, setGroupPicked] = useState([]);
  const [groupHits, setGroupHits] = useState([]);
  const [groupSearchEmpty, setGroupSearchEmpty] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addHits, setAddHits] = useState([]);
  const [addQuery, setAddQuery] = useState("");
  const [addError, setAddError] = useState("");
  const [addEmpty, setAddEmpty] = useState("");
  const [busy, setBusy] = useState(false);
  const avatarInput = useRef(null);
  const groupPhotoInput = useRef(null);
  const scroller = useRef(null);
  const typingTimer = useRef(null);

  const active = conversations.find((c) => c.id === activeId) || null;

  const refreshConvos = useCallback(async () => {
    const data = await api.conversations();
    setConversations(data);
    setPresence((prev) => {
      const next = { ...prev };
      for (const c of data) for (const m of c.members) next[m.id] = m.online;
      return next;
    });
    return data;
  }, []);

  useEffect(() => {
    refreshConvos();
    api.notifications().then(setNotifications).catch(() => {});
  }, [refreshConvos]);

  useEffect(() => {
    if (!activeId) return undefined;
    let cancelled = false;
    api.messages(activeId).then((rows) => {
      if (!cancelled) setMessages(rows);
    });
    api.markRead(activeId).then(() => refreshConvos()).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeId, refreshConvos]);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [messages, typing, activeId]);

  const onEvent = useCallback(
    (event) => {
      if (event.type === "presence") {
        setPresence((p) => ({ ...p, [event.user_id]: event.status === "online" }));
      }
      if (event.type === "typing" && event.user_id !== user.id) {
        setTyping((t) => ({
          ...t,
          [event.conversation_id]: event.is_typing
            ? { user_id: event.user_id, until: Date.now() + 4000 }
            : null,
        }));
      }
      if (event.type === "message" && event.payload) {
        const msg = event.payload;
        if (msg.conversation_id === activeId) {
          setMessages((rows) => (rows.some((m) => m.id === msg.id) ? rows : [...rows, msg]));
          api.markRead(activeId).catch(() => {});
        }
        refreshConvos();
      }
      if (event.type === "conversation.upsert") refreshConvos();
      if (event.type === "read") refreshConvos();
      if (event.type === "notification") {
        setNotifications((n) => [{ ...event, id: event.message_id, is_read: false }, ...n]);
      }
    },
    [activeId, refreshConvos, user.id]
  );

  const socket = useSocket(token, onEvent);

  useEffect(() => {
    const id = setInterval(() => {
      setTyping((t) => {
        const next = { ...t };
        for (const key of Object.keys(next)) {
          if (next[key] && next[key].until < Date.now()) next[key] = null;
        }
        return next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  async function searchPeople(value) {
    setQuery(value);
    if (value.trim().length < 1) {
      setHits([]);
      setSearchEmpty("");
      return;
    }
    const found = await api.searchUsers(value.trim());
    setHits(found);
    setSearchEmpty(found.length ? "" : `No registered user matches “${value.trim()}”`);
  }

  async function openDirect(userId) {
    const conv = await api.createDirect(userId);
    await refreshConvos();
    setActiveId(conv.id);
    setHits([]);
    setQuery("");
    setSearchEmpty("");
  }

  async function createGroup(e) {
    e.preventDefault();
    if (groupPicked.length === 0) {
      setGroupSearchEmpty("Add at least one person who already has an account");
      return;
    }
    const conv = await api.createGroup(
      groupName,
      groupPicked.map((p) => p.id)
    );
    await refreshConvos();
    setActiveId(conv.id);
    setGroupOpen(false);
    setGroupName("");
    setGroupPicked([]);
    setGroupHits([]);
  }

  async function searchGroupPeople(value) {
    const q = value.trim();
    if (!q) {
      setGroupHits([]);
      setGroupSearchEmpty("");
      return;
    }
    const found = await api.searchUsers(q);
    setGroupHits(found);
    setGroupSearchEmpty(found.length ? "" : `No account named “${q}”. They must register first.`);
  }

  async function searchToAdd(value) {
    setAddQuery(value);
    const q = value.trim();
    if (!q) {
      setAddHits([]);
      setAddEmpty("");
      return;
    }
    const found = await api.searchUsers(q);
    const memberIds = new Set((active?.members || []).map((m) => Number(m.id)));
    const available = found.filter((h) => !memberIds.has(Number(h.id)));
    setAddHits(available);
    setAddEmpty(available.length ? "" : `No registered user named “${q}” to add`);
  }

  async function addPerson(userId) {
    if (!activeId) return;
    setAddError("");
    try {
      await api.addMembers(activeId, [userId]);
      await refreshConvos();
      setAddHits((rows) => rows.filter((h) => Number(h.id) !== Number(userId)));
    } catch (err) {
      setAddError(err.message);
    }
  }

  async function addByExactName(e) {
    e.preventDefault();
    const name = addQuery.trim();
    if (!name) return;
    setAddError("");
    try {
      const found = await api.lookupUser(name);
      await addPerson(found.id);
      setAddQuery("");
      setAddHits([]);
      setAddEmpty("");
    } catch (err) {
      setAddError(err.message);
    }
  }

  async function onAvatar(e) {
    const photo = e.target.files?.[0];
    e.target.value = "";
    if (!photo) return;
    const next = await api.uploadAvatar(photo);
    updateUser(next);
    await refreshConvos();
  }

  async function onGroupPhoto(e) {
    const photo = e.target.files?.[0];
    e.target.value = "";
    if (!photo || !activeId) return;
    await api.uploadGroupAvatar(activeId, photo);
    await refreshConvos();
  }

  function onDraft(value) {
    setDraft(value);
    if (!activeId) return;
    socket.send({ type: "typing", conversation_id: activeId, is_typing: true });
    clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => {
      socket.send({ type: "typing", conversation_id: activeId, is_typing: false });
    }, 1200);
  }

  async function send(e) {
    e.preventDefault();
    if (!activeId || busy) return;
    if (!draft.trim() && !file) return;
    setBusy(true);
    try {
      const msg = await api.sendMessage(activeId, { content: draft, file });
      setMessages((rows) => (rows.some((m) => m.id === msg.id) ? rows : [...rows, msg]));
      setDraft("");
      setFile(null);
      await refreshConvos();
    } finally {
      setBusy(false);
    }
  }

  const unreadNotifs = notifications.filter((n) => !n.is_read).length;
  const typingState = activeId ? typing[activeId] : null;
  const typingName = useMemo(() => {
    if (!typingState || !active) return null;
    return active.members.find((m) => m.id === typingState.user_id)?.username;
  }, [typingState, active]);

  const peerOnline =
    active?.type === "direct"
      ? presence[active.members.find((m) => m.id !== user.id)?.id]
      : active?.members.some((m) => m.id !== user.id && presence[m.id]);

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="side-head">
          <div className="me">
            <button type="button" className="avatar-btn" onClick={() => avatarInput.current?.click()} title="Change photo">
              <Avatar src={user.avatar_url} name={user.username} />
            </button>
            <input ref={avatarInput} type="file" accept="image/*" hidden onChange={onAvatar} />
            <div>
              <p className="eyebrow">Relay</p>
              <strong>{user.username}</strong>
            </div>
          </div>
          <button className="ghost" onClick={logout} type="button">
            Out
          </button>
        </header>
        <div className="search-box">
          <input placeholder="Find people" value={query} onChange={(e) => searchPeople(e.target.value)} />
          <button type="button" className="ghost" onClick={() => setGroupOpen(true)}>
            New group
          </button>
        </div>
        {searchEmpty && <p className="hint">{searchEmpty}</p>}
        {hits.length > 0 && (
          <ul className="hits">
            {hits.map((h) => (
              <li key={h.id}>
                <button type="button" onClick={() => openDirect(h.id)}>
                  <Avatar src={h.avatar_url} name={h.username} />
                  <span className={`dot ${h.online ? "on" : ""}`} />
                  {h.username}
                </button>
              </li>
            ))}
          </ul>
        )}
        <ul className="convo-list">
          {conversations.map((c) => {
            const label = titleFor(c, user.id);
            return (
              <li key={c.id} className={c.id === activeId ? "active" : ""}>
                <button type="button" onClick={() => setActiveId(c.id)}>
                  <Avatar src={convoPhoto(c, user.id)} name={label} />
                  <span className="meta">
                    <span className="row">
                      <strong>{label}</strong>
                      {c.unread_count > 0 && <em className="badge">{c.unread_count}</em>}
                    </span>
                    <small>
                      {c.last_message ? c.last_message.content || c.last_message.file_name : "No messages yet"}
                    </small>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {unreadNotifs > 0 && (
          <p className="notif-strip">
            {unreadNotifs} unread notification{unreadNotifs === 1 ? "" : "s"} while you were away
          </p>
        )}
      </aside>

      <section className="thread">
        {!active ? (
          <div className="empty">Select a conversation or search for someone to start chatting.</div>
        ) : (
          <>
            <header className="thread-head">
              <div className="me">
                {active.type === "group" ? (
                  <button type="button" className="avatar-btn" onClick={() => groupPhotoInput.current?.click()} title="Group photo">
                    <Avatar className="lg" src={active.avatar_url} name={titleFor(active, user.id)} />
                  </button>
                ) : (
                  <Avatar
                    className="lg"
                    src={active.members.find((m) => m.id !== user.id)?.avatar_url}
                    name={titleFor(active, user.id)}
                  />
                )}
                <input ref={groupPhotoInput} type="file" accept="image/*" hidden onChange={onGroupPhoto} />
                <div>
                  <h2>{titleFor(active, user.id)}</h2>
                  <p className="muted">
                    <span className={`dot ${peerOnline ? "on" : ""}`} />
                    {active.type === "group"
                      ? `${active.members.map((m) => m.username).join(", ")} · ${active.members.length} members`
                      : peerOnline
                        ? "Online"
                        : "Offline"}
                  </p>
                </div>
              </div>
              {active.type === "group" && (
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    setAddError("");
                    setAddHits([]);
                    setAddQuery("");
                    setAddEmpty("");
                    setAddOpen(true);
                  }}
                >
                  Add people
                </button>
              )}
            </header>
            <div className="messages" ref={scroller}>
              {messages.map((m) => {
                const mine = Number(m.sender_id) === Number(user.id);
                const readers = (active.members || []).filter(
                  (mem) =>
                    Number(mem.id) !== Number(user.id) &&
                    mem.last_read_at &&
                    new Date(mem.last_read_at) >= new Date(m.created_at)
                );
                return (
                  <article key={m.id} className={`msg-row ${mine ? "mine" : "theirs"}`}>
                    {!mine && <Avatar src={m.sender_avatar} name={m.sender_username} className="sm" />}
                    <div className="bubble">
                      {!mine && <cite>{m.sender_username}</cite>}
                      {m.content && <p>{m.content}</p>}
                      {m.message_type === "image" && m.file_url && (
                        <a href={m.file_url} target="_blank" rel="noreferrer">
                          <img src={m.file_url} alt={m.file_name || "image"} />
                        </a>
                      )}
                      {m.message_type === "file" && m.file_url && (
                        <a className="file-link" href={m.file_url} target="_blank" rel="noreferrer">
                          {m.file_name || "Download file"}
                        </a>
                      )}
                      <time>
                        {timeLabel(m.created_at)}
                        {mine && readers.length > 0 ? " · Read" : mine ? " · Sent" : ""}
                      </time>
                    </div>
                  </article>
                );
              })}
              {typingName && <p className="typing">{typingName} is typing…</p>}
            </div>
            <form className="composer" onSubmit={send}>
              <label className="attach">
                +
                <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              </label>
              <input value={draft} onChange={(e) => onDraft(e.target.value)} placeholder="Message" />
              <button type="submit" disabled={busy}>
                Send
              </button>
            </form>
            {file && <p className="file-preview">Attached: {file.name}</p>}
          </>
        )}
      </section>

      {addOpen && (
        <div className="modal" onClick={() => setAddOpen(false)}>
          <form className="auth-card" onClick={(e) => e.stopPropagation()} onSubmit={addByExactName}>
            <h2>Add to {titleFor(active, user.id)}</h2>
            <p className="muted">Only people who already registered can be added.</p>
            <p className="muted">Already in: {(active?.members || []).map((m) => m.username).join(", ")}</p>
            <label>
              Search registered username
              <input value={addQuery} placeholder="e.g. manja" onChange={(e) => searchToAdd(e.target.value)} autoFocus />
            </label>
            {addEmpty && <p className="hint">{addEmpty}</p>}
            <ul className="hits">
              {addHits.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => addPerson(h.id)}>
                    <Avatar src={h.avatar_url} name={h.username} />
                    Add {h.username}
                  </button>
                </li>
              ))}
            </ul>
            {addError && <p className="error">{addError}</p>}
            <button type="submit">Add if this exact username exists</button>
            <button type="button" className="ghost" onClick={() => setAddOpen(false)}>
              Done
            </button>
          </form>
        </div>
      )}
      {groupOpen && (
        <div className="modal" onClick={() => setGroupOpen(false)}>
          <form className="auth-card" onClick={(e) => e.stopPropagation()} onSubmit={createGroup}>
            <h2>New group</h2>
            <label>
              Name
              <input value={groupName} onChange={(e) => setGroupName(e.target.value)} required />
            </label>
            <label>
              Add registered people
              <input placeholder="Search usernames" onChange={(e) => searchGroupPeople(e.target.value)} />
            </label>
            {groupSearchEmpty && <p className="hint">{groupSearchEmpty}</p>}
            <ul className="hits">
              {groupHits.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => {
                      if (!groupPicked.some((p) => p.id === h.id)) setGroupPicked([...groupPicked, h]);
                    }}
                  >
                    <Avatar src={h.avatar_url} name={h.username} />
                    {h.username}
                  </button>
                </li>
              ))}
            </ul>
            <p className="muted">{groupPicked.map((p) => p.username).join(", ") || "No members yet — pick from search"}</p>
            <button type="submit">Create group</button>
          </form>
        </div>
      )}
    </div>
  );
}
