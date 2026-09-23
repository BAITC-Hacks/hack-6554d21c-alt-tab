export function Icon({ name, className = '' }: { name: 'mic' | 'send' | 'plus' | 'trace' | 'play' | 'stop' | 'check' | 'arrow' | 'headphones' | 'close'; className?: string }) {
  const paths = {
    mic: <><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></>,
    send: <><path d="m3 3 19 9-19 9 4-9-4-9ZM7 12h15"/></>,
    plus: <path d="M12 5v14M5 12h14"/>, trace: <><path d="M5 5h5v5H5zM14 14h5v5h-5zM7.5 10v6.5H14M10 7.5h7V14"/></>,
    play: <path d="m8 4 12 8-12 8V4Z"/>, stop: <rect x="5" y="5" width="14" height="14" rx="2"/>,
    check: <path d="m5 12 4 4L19 6"/>, arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    headphones: <><path d="M4 14v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="12" width="4" height="8" rx="2"/><rect x="17" y="12" width="4" height="8" rx="2"/></>, close: <path d="m6 6 12 12M6 18 18 6"/>,
  }
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
