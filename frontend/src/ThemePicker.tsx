import { Monitor, Moon, Sun } from 'lucide-react';
import { useState } from 'react';

const themes = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
] as const;
type Theme = typeof themes[number]['value'];

export default function ThemePicker() {
  const [theme, setTheme] = useState<Theme>(() => {
    const active = document.documentElement.dataset.theme;
    return active === 'light' || active === 'dark' ? active : 'system';
  });

  function change(next: Theme) {
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem('open-agent-theme', next);
    } catch {
      // The theme still applies for the current session.
    }
  }

  return <section className="card form-card appearance-card">
    <div><h2>Appearance</h2><p className="muted">Choose your workspace theme.</p></div>
    <div className="theme-options" role="group" aria-label="Appearance">
      {themes.map(({value, label, icon: Icon}) =>
        <button key={value} type="button" aria-pressed={theme === value} onClick={() => change(value)}>
          <Icon size={16} aria-hidden="true"/>{label}
        </button>
      )}
    </div>
  </section>;
}
