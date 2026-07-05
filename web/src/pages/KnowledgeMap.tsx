/**
 * Page D: Knowledge Map
 *
 * Interactive matrix: rows = info items, columns = characters.
 * Cell color encodes state (know=green / obs=amber / leak=red / empty=light).
 * Click cell → bottom detail panel with leak alert.
 *
 * Suprematist style: bold borders, colored fills, monospace info IDs.
 */

import { useState } from 'react'
import type { SensitivityLevel } from '@/types/ktsl'

type CellState = 'know' | 'obs' | 'leak' | 'empty' | 'keeper'

interface Cell {
  state: CellState
  source?: string
  sensitivity: SensitivityLevel
}

interface InfoRow {
  infoId: string
  title: string
  sensitivity: SensitivityLevel
  cells: Record<string, Cell>
}

const characters = ['佐藤', '李', '王', 'NPC_医生']

const infoRows: InfoRow[] = [
  {
    infoId: 'info_01',
    title: '警察搜查令',
    sensitivity: 'public',
    cells: {
      '佐藤': { state: 'know', source: 'init', sensitivity: 'public' },
      '李': { state: 'know', source: 'init', sensitivity: 'public' },
      '王': { state: 'know', source: 'init', sensitivity: 'public' },
      'NPC_医生': { state: 'empty', sensitivity: 'public' },
    },
  },
  {
    infoId: 'info_07',
    title: '档案记录',
    sensitivity: 'low',
    cells: {
      '佐藤': { state: 'know', source: '#S001', sensitivity: 'low' },
      '李': { state: 'obs', source: '#S003', sensitivity: 'low' },
      '王': { state: 'empty', sensitivity: 'low' },
      'NPC_医生': { state: 'empty', sensitivity: 'low' },
    },
  },
  {
    infoId: 'info_09',
    title: '医生深夜行踪',
    sensitivity: 'medium',
    cells: {
      '佐藤': { state: 'empty', sensitivity: 'medium' },
      '李': { state: 'know', source: '#S002', sensitivity: 'medium' },
      '王': { state: 'empty', sensitivity: 'medium' },
      'NPC_医生': { state: 'empty', sensitivity: 'medium' },
    },
  },
  {
    infoId: 'info_12',
    title: '老宅地下室尸体',
    sensitivity: 'high',
    cells: {
      '佐藤': { state: 'know', source: '#S005', sensitivity: 'high' },
      '李': { state: 'leak', source: '#S007', sensitivity: 'high' },
      '王': { state: 'empty', sensitivity: 'high' },
      'NPC_医生': { state: 'know', source: 'init', sensitivity: 'high' },
    },
  },
  {
    infoId: 'info_15',
    title: '真凶身份',
    sensitivity: 'keeper',
    cells: {
      '佐藤': { state: 'empty', sensitivity: 'keeper' },
      '李': { state: 'empty', sensitivity: 'keeper' },
      '王': { state: 'empty', sensitivity: 'keeper' },
      'NPC_医生': { state: 'keeper', sensitivity: 'keeper' },
    },
  },
]

function cellStyle(state: CellState): string {
  switch (state) {
    case 'know': return 'bg-forest text-white'
    case 'obs': return 'bg-gold text-ink'
    case 'leak': return 'bg-brick text-white'
    case 'keeper': return 'bg-ink text-white'
    default: return 'bg-[#FAFAF8]'
  }
}

function cellIcon(state: CellState): string {
  switch (state) {
    case 'know': return '📖'
    case 'obs': return '👁'
    case 'leak': return '⚠'
    case 'keeper': return '🖤'
    default: return ''
  }
}

function cellLabel(state: CellState): string {
  switch (state) {
    case 'know': return '知道'
    case 'obs': return '看到'
    case 'leak': return '泄露'
    case 'keeper': return 'keeper only'
    default: return ''
  }
}

function sensitivityClass(sens: SensitivityLevel): string {
  switch (sens) {
    case 'low': return 'text-forest'
    case 'medium': case 'public': return 'text-amber-800'
    case 'high': return 'text-brick'
    case 'keeper': return 'text-ink'
    default: return 'text-muted'
  }
}

interface SelectedCell {
  infoId: string
  character: string
}

export default function KnowledgeMap() {
  const [selected, setSelected] = useState<SelectedCell>({ infoId: 'info_12', character: '李' })

  const row = infoRows.find((r) => r.infoId === selected.infoId)
  const cell = row ? row.cells[selected.character] : undefined

  return (
    <div>
      <h1 className="text-[22px] font-black">Knowledge Map</h1>
      <p className="mb-7 mt-1.5 font-body text-[11px] uppercase tracking-[2px] text-muted">
        Character × Info Matrix · police_hospital · {infoRows.length} info items
      </p>

      {/* Toolbar */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <select className="border-2 border-line bg-white px-3 py-2 font-body text-sm outline-none focus:border-indigo">
          <option>全部角色</option>
          {characters.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select className="border-2 border-line bg-white px-3 py-2 font-body text-sm outline-none focus:border-indigo">
          <option>全部敏感度</option>
          <option>public</option>
          <option>low</option>
          <option>medium</option>
          <option>high</option>
          <option>keeper</option>
        </select>
        <input
          type="text"
          placeholder="搜索 info 内容..."
          className="min-w-[200px] border-2 border-line bg-white px-3 py-2 font-body text-sm outline-none focus:border-indigo"
        />
        <div className="ml-auto flex gap-3.5 font-body text-[10px] text-muted">
          <span><span className="mr-1 inline-block h-2.5 w-2.5 border-2 border-ink bg-forest align-middle" />知道</span>
          <span><span className="mr-1 inline-block h-2.5 w-2.5 border-2 border-ink bg-gold align-middle" />看到</span>
          <span><span className="mr-1 inline-block h-2.5 w-2.5 border-2 border-ink bg-brick align-middle" />泄露</span>
        </div>
      </div>

      {/* Matrix */}
      <div className="border-[3px] border-ink">
        {/* Header row */}
        <div className="grid grid-cols-[200px_1fr] border-b-[3px] border-ink bg-paper">
          <div className="border-r-[3px] border-ink p-3.5 text-[11px] font-black uppercase tracking-[2px]">
            Info ╱ Character
          </div>
          <div className={`grid grid-cols-${characters.length} grid-cols-4`}>
            {characters.map((c) => (
              <div key={c} className="border-r border-line px-3 py-2.5 text-center last:border-r-0">
                <div className="text-xs font-black">{c}</div>
                <div className="font-body text-[9px] tracking-wider text-muted">
                  {Object.values(infoRows).filter((r) => r.cells[c]?.state !== 'empty').length} known
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Info rows */}
        {infoRows.map((r) => (
          <div
            key={r.infoId}
            className={`grid grid-cols-[200px_1fr] border-b-2 border-line last:border-b-0 ${
              r.infoId === 'info_12' ? 'outline outline-3 outline-brick -outline-offset-3' : ''
            }`}
          >
            {/* Row label */}
            <div
              className={`border-r-[3px] border-ink p-3.5 flex flex-col justify-center ${
                r.infoId === 'info_07' ? 'bg-white border-l-[6px] border-l-indigo' : 'bg-sand'
              }`}
            >
              <span className="mb-0.5 font-mono text-[11px] font-black text-indigo">{r.infoId}</span>
              <span className="mb-1 text-xs font-bold">{r.title}</span>
              <span className={`font-body text-[9px] font-bold uppercase tracking-wider ${sensitivityClass(r.sensitivity)}`}>
                {r.sensitivity === 'high' ? `${r.sensitivity} ⚠` : r.sensitivity}
              </span>
            </div>
            {/* Cells */}
            <div className={`grid grid-cols-${characters.length} grid-cols-4`}>
              {characters.map((c) => {
                const cellData = r.cells[c]
                if (!cellData || cellData.state === 'empty') {
                  return (
                    <div key={c} className="flex min-h-[56px] flex-col items-center justify-center border-r border-line bg-[#FAFAF8] text-center text-[10px] text-line last:border-r-0" />
                  )
                }
                const isSelected = selected.infoId === r.infoId && selected.character === c
                return (
                  <button
                    type="button"
                    key={c}
                    onClick={() => setSelected({ infoId: r.infoId, character: c })}
                    className={`flex min-h-[56px] flex-col items-center justify-center border-r border-line px-2 py-2 text-center text-[10px] last:border-r-0 ${cellStyle(cellData.state)} ${
                      isSelected ? 'ring-2 ring-inset ring-indigo' : ''
                    }`}
                  >
                    <span className="text-sm leading-none">{cellIcon(cellData.state)}</span>
                    <>
                      <span className="font-bold">{cellLabel(cellData.state)}</span>
                      {cellData.source && (
                        <span className="font-mono text-[8px] opacity-80">{cellData.source}</span>
                      )}
                    </>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Detail panel */}
      {row && cell && (
        <div className="mt-7 border-[3px] border-indigo bg-white grid grid-cols-2 gap-6 p-6">
          <div>
            <div className="mb-2 font-mono text-[13px] font-black text-indigo">
              {row.infoId} × {selected.character}
            </div>
            <div className="mb-2 text-xl font-black leading-tight">{row.title}</div>
            <div className="mb-3 border border-line bg-sand p-3 font-body text-[13px] leading-relaxed text-ink">
              &quot;地下室的角落藏着一具穿着校服的女学生尸体已经3天了，手脚有被捆绑的痕迹，死因是窒息。身边散落着几张撕碎的日记纸片。&quot;
            </div>
            <div className="font-body text-[11px] leading-relaxed text-muted">
              <strong className="text-ink">敏感度:</strong> {row.sensitivity.toUpperCase()}<br />
              <strong className="text-ink">应知道:</strong> {cell.state === 'leak' ? `否（${selected.character} 当前不应该知道这件事）` : '是'}<br />
              <strong className="text-ink">获得方式:</strong> {cell.state === 'leak' ? `暗示 (partial) — 从事件 ${cell.source} 佐藤的对话内容推断` : `${cell.source} 直接获得`}
            </div>
          </div>
          {cell.state === 'leak' ? (
            <div>
              <div className="mb-2 text-[10px] font-black uppercase tracking-[2px] text-brick">
                ⚠ Leak Alert
              </div>
              <div className={`mb-2 border-l-4 border-brick bg-paper px-3.5 py-2.5 text-xs font-bold text-brick`}>
                1. {selected.character} 尚未被正式授权知道 {row.infoId}
              </div>
              <div className="mb-2 border-l-4 border-brick bg-paper px-3.5 py-2.5 text-xs font-bold text-brick">
                2. 佐藤在事件 {cell.source} 中的对话暗示了&quot;地下室&quot;和&quot;尸体&quot;
              </div>
              <div className="mb-2 border-l-4 border-brick bg-paper px-3.5 py-2.5 text-xs font-bold text-brick">
                3. 根据 KTSL Filter 层规则，高敏感信息不应通过暗示方式传播
              </div>
              <div className="mt-2 border border-forest bg-white px-3 py-2 font-body text-xs leading-relaxed text-forest">
                💡 建议: 让佐藤在接下来的对话中避免提及此信息，或 KP 主动发起 {row.infoId} 的正式解密流程
              </div>
            </div>
          ) : (
            <div>
              <div className="mb-2 text-[10px] font-black uppercase tracking-[2px] text-forest">
                ✓ Authorized
              </div>
              <div className="mb-2 border border-forest bg-white px-3 py-2 text-xs text-forest">
                {selected.character} 已被正式授权知道此信息。
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
