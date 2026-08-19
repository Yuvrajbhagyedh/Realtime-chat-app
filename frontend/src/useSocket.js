import { useEffect, useRef } from "react";

export function useSocket(token, onEvent) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const wsRef = useRef(null);

  useEffect(() => {
    if (!token) return undefined;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws?token=${encodeURIComponent(token)}`;
    let closed = false;
    let ping;

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          handler.current(JSON.parse(ev.data));
        } catch {
          /* ignore */
        }
      };
      ws.onopen = () => {
        ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        }, 20000);
      };
      ws.onclose = () => {
        clearInterval(ping);
        if (!closed) setTimeout(connect, 1500);
      };
    }

    connect();
    return () => {
      closed = true;
      clearInterval(ping);
      wsRef.current?.close();
    };
  }, [token]);

  return {
    send(payload) {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
    },
  };
}
