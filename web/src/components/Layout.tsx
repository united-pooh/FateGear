/**
 * Two-column layout: fixed 64px sidebar on the left, flexible main content on the right.
 *
 * Used as the root layout wrapper in App.tsx. All page components render
 * inside the main content area. Suprematist warm background.
 */

import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg">
      <Sidebar />
      <main className="ml-16 flex-1 overflow-y-auto p-9 pb-16 relative z-10 suprematist-accent">
        <Outlet />
      </main>
    </div>
  )
}
