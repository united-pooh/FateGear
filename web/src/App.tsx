/**
 * Root application component.
 *
 * Sets up react-router-dom Routes + Route mapping for all 7 pages,
 * wrapped in the two-column Layout (Sidebar + Main Content).
 */

import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Session from '@/pages/Session'
import Timeline from '@/pages/Timeline'
import KnowledgeMap from '@/pages/KnowledgeMap'
import BarriersCouplings from '@/pages/BarriersCouplings'
import Reports from '@/pages/Reports'
import Modules from '@/pages/Modules'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="/session/:sessionId" element={<Session />} />
        <Route path="/session" element={<Session />} />
        <Route path="/timeline/:sessionId?" element={<Timeline />} />
        <Route path="/knowledge/:sessionId?" element={<KnowledgeMap />} />
        <Route path="/barriers/:sessionId?" element={<BarriersCouplings />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/modules" element={<Modules />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
