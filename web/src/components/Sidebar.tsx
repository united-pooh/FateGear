/**
 * Fixed 64px navigation sidebar.
 *
 * Deep indigo background with amber logo square "K" and 7 navigation icons.
 * Active item has a 3px amber vertical bar on the left.
 * Uses react-router-dom NavLink for routing.
 */

import { NavLink } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
  icon: string
}

const items: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: '▦' },
  { to: '/session', label: 'Session', icon: '▶' },
  { to: '/timeline', label: 'Timeline', icon: '≡' },
  { to: '/knowledge', label: 'Knowledge', icon: '⊞' },
  { to: '/barriers', label: 'Barriers', icon: '⊟' },
  { to: '/reports', label: 'Reports', icon: '◈' },
  { to: '/modules', label: 'Modules', icon: '⚙' },
]

export default function Sidebar() {
  return (
    <nav className="fixed top-0 left-0 z-50 flex h-screen w-16 flex-col items-center bg-indigo pt-5 gap-1">
      {/* Logo */}
      <div className="mb-6 flex h-10 w-10 items-center justify-center bg-amber text-lg font-black text-indigo">
        K
      </div>
      {/* Nav items */}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          title={item.label}
          className={({ isActive }) =>
            `relative flex h-11 w-11 items-center justify-center text-lg transition-colors ${
              isActive
                ? 'bg-white/10 text-amber'
                : 'text-white/60 hover:bg-white/8 hover:text-amber'
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <span className="absolute left-0 top-2 h-7 w-[3px] bg-amber" />
              )}
              {item.icon}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
