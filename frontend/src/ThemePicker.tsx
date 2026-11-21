import {useState} from 'react';

type Theme = 'system' | 'light' | 'dark';

export default function ThemePicker() {
  const [theme, setTheme] = useState<Theme>(() => {
    const active = document.documentElement.dataset.theme;
    return active === 'light' || active === 'dark' ? active : 'system';
  });
  function change(next: Theme) {
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try { localStorage.setItem('open-agent-theme', next); } catch { /* Session-only preference. */ }
  }
  return <label className="theme-picker">Appearance
    <select value={theme} onChange={event => change(event.target.value as Theme)}>
      <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
  </label>;
}
