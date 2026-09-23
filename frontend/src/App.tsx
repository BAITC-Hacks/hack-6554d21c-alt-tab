export function App() {
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/">saqta<span>insurance</span></a><span>Голосовой симулятор</span><span className="badge">Live · подключение к серверу</span></header>
    <main><div className="page-heading"><div><span className="eyebrow">Клиент и голосовой помощник</span><h1>Разговор, который понятен.</h1><p>Говорите на русском или казахском. Следите за логикой каждого ответа.</p></div></div>
      <div className="workspace"><section className="conversation panel"><h2>Диалог</h2><p>Настройка сессии и голосового ввода…</p></section><aside className="trace panel"><h2>Логика ответа</h2><p>Здесь появится трассировка выбранной реплики.</p></aside></div>
    </main>
  </div>
}
