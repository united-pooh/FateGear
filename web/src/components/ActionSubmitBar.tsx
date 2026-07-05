/**
 * Session page — bottom-fixed action submission bar.
 *
 * Phase 8: will wire to useSubmitEventMutation, add autocomplete for
 * actors/scenes, and show inline validation feedback.
 */

import { useState } from 'react'
import type { ActionInput, Visibility } from '@/types/ktsl'

export interface ActionSubmitBarProps {
  sessionId: string
  onSubmit?: (input: ActionInput) => void
}

export default function ActionSubmitBar({ sessionId: _sessionId, onSubmit }: ActionSubmitBarProps) {
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [sceneId, setSceneId] = useState('')
  const [visibility, setVisibility] = useState<Visibility>('public')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!action || !actor || !sceneId) return
    onSubmit?.({ action, actor, scene_id: sceneId, visibility })
    setAction('')
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="fixed bottom-0 left-16 right-0 border-t border-gray-200 bg-white p-4 shadow-lg"
    >
      <div className="flex flex-col gap-2">
        <input
          type="text"
          placeholder="行动描述..."
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="角色"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            className="w-32 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <input
            type="text"
            placeholder="场景 ID"
            value={sceneId}
            onChange={(e) => setSceneId(e.target.value)}
            className="w-40 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as Visibility)}
            className="rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="public">public</option>
            <option value="private">private</option>
            <option value="keeper">keeper</option>
          </select>
          <div className="flex-1" />
          <button
            type="button"
            className="rounded px-4 py-2 text-sm text-gray-600 hover:bg-gray-100"
          >
            取消
          </button>
          <button
            type="submit"
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            提交行动 →
          </button>
        </div>
      </div>
    </form>
  )
}
