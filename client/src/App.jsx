import { useEffect, useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { api } from './api.js';
import Home from './pages/Home.jsx';
import Dataset from './pages/Dataset.jsx';

function Status() {
  const [h, setH] = useState(null);
  useEffect(() => {
    const tick = () => api.health().then(setH).catch(() => setH({ server: 'down' }));
    tick(); const t = setInterval(tick, 8000); return () => clearInterval(t);
  }, []);
  if (!h) return null;
  const serverOk = h.server === 'ok';
  return (
    <span className="status" title={h.dataDir || ''}>
      <span className={`dot ${serverOk ? 'ok' : 'bad'}`} />server
      <span style={{ marginLeft: 12 }} className={`dot ${h.engine ? 'ok' : 'bad'}`} />engine
      {h.store && <span style={{ marginLeft: 12 }}>store: {h.store}</span>}
    </span>
  );
}

export default function App() {
  return (
    <>
      <header className="top">
        <Link to="/">Behavioral Analytics</Link>
        <span className="spacer" />
        <Status />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/d/:id" element={<Dataset />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Go home</Link></p>} />
        </Routes>
      </main>
    </>
  );
}
