/**
 * Knowledge Map page — interactive matrix of characters × info items.
 *
 * Phase 8: will add cell click → detail panel, color-coded sensitivity,
 * and leak indicators.
 */

import type { KnowledgeItemView } from '@/types/ktsl'

export interface KnowledgeMatrixProps {
  knowledgeMap: Record<string, KnowledgeItemView[]>
}

const sensitivityColor: Record<string, string> = {
  public: 'bg-gray-100 text-gray-600',
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-red-100 text-red-700',
  keeper: 'bg-purple-100 text-purple-700',
}

export default function KnowledgeMatrix({ knowledgeMap }: KnowledgeMatrixProps) {
  const characters = Object.keys(knowledgeMap)
  const allInfoIds = Array.from(
    new Set(
      Object.values(knowledgeMap).flatMap((items) => items.map((i) => i.info_id)),
    ),
  )

  if (characters.length === 0) {
    return (
      <p className="text-gray-500">No knowledge data available for this session.</p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border bg-gray-50 px-3 py-2 text-left">Info \ Role</th>
            {characters.map((char) => (
              <th key={char} className="border bg-gray-50 px-3 py-2 text-left">
                {char}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {allInfoIds.map((infoId) => (
            <tr key={infoId}>
              <td className="border px-3 py-2 font-mono text-xs">{infoId}</td>
              {characters.map((char) => {
                const items = knowledgeMap[char] ?? []
                const match = items.find((i) => i.info_id === infoId)
                if (!match) {
                  return (
                    <td key={char} className="border px-3 py-2 text-gray-300">
                      ·
                    </td>
                  )
                }
                return (
                  <td key={char} className="border px-3 py-2">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-xs ${
                        sensitivityColor[match.sensitivity] ?? ''
                      }`}
                    >
                      {match.kind === 'know' ? '📖' : '👁'} {match.sensitivity}
                      {match.leaked && ' ⚠'}
                    </span>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
