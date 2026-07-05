/**
 * Page: Modules
 *
 * Browse, validate, and manage KTSL fixture modules. Suprematist style:
 * bold diamond accents, geometric action buttons.
 */

import { useState } from 'react'

interface ModuleItem {
  id: string
  title: string
  description: string
  sceneCount: number
  barrierCount: number
  eventCount: number
  validationStatus: 'valid' | 'warning' | 'none'
}

const modules: ModuleItem[] = [
  {
    id: 'police_hospital_old_house',
    title: '警察·医院·老宅',
    description: '三级场景模组 / police·hospital·old_house',
    sceneCount: 4,
    barrierCount: 3,
    eventCount: 12,
    validationStatus: 'valid',
  },
  {
    id: 'simple_library',
    title: 'simple_library',
    description: '二级场景 / 图书馆谜题',
    sceneCount: 2,
    barrierCount: 1,
    eventCount: 8,
    validationStatus: 'valid',
  },
  {
    id: 'airport_chase',
    title: 'airport_chase',
    description: '单场景 / 机场追逐模组',
    sceneCount: 1,
    barrierCount: 0,
    eventCount: 6,
    validationStatus: 'warning',
  },
]

function validationBadge(status: ModuleItem['validationStatus']) {
  switch (status) {
    case 'valid':
      return { label: '✓ VALID', cls: 'border-forest bg-forest/10 text-forest' }
    case 'warning':
      return { label: '⚠ WARN', cls: 'border-amber-700 bg-gold/10 text-amber-800' }
    default:
      return { label: '— NONE', cls: 'border-line bg-sand text-muted' }
  }
}

export default function Modules() {
  const [importText, setImportText] = useState('')

  return (
    <div>
      {/* Header */}
      <h1 className="mb-1 text-[22px] font-black">Modules</h1>
      <p className="mb-8 font-body text-[11px] uppercase tracking-[2px] text-muted">
        Manage KTSL fixture modules · {modules.length} loaded
      </p>

      {/* Module list */}
      <div className="mb-10">
        <div className="relative mb-4 pl-4 text-[10px] font-black uppercase tracking-[3px] text-muted">
          <span className="absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 bg-primary" />
          Fixture Modules
        </div>
        <div className="flex flex-col gap-3">
          {modules.map((m) => {
            const badge = validationBadge(m.validationStatus)
            return (
              <div
                key={m.id}
                className="border-2 border-line bg-white p-5 transition-colors hover:bg-paper"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="mb-1 flex items-center gap-3">
                      <span className="font-mono text-[13px] font-black text-indigo">
                        {m.id}
                      </span>
                      <span
                        className={`border px-2 py-0.5 font-body text-[10px] font-bold ${badge.cls}`}
                      >
                        {badge.label}
                      </span>
                    </div>
                    <div className="text-[15px] font-black">{m.title}</div>
                    <div className="mt-1 font-body text-[11px] text-muted">
                      {m.description}
                    </div>
                    <div className="mt-3 flex gap-4 font-mono text-[11px] text-muted">
                      <span>{m.sceneCount} scenes</span>
                      <span>{m.eventCount} events</span>
                      <span>{m.barrierCount} barriers</span>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2">
                    <button
                      type="button"
                      className="border-2 border-ink bg-white px-4 py-2 text-[11px] font-black transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:bg-indigo hover:text-bg hover:shadow-[4px_4px_0_#F59E0B]"
                    >
                      Validate
                    </button>
                    <button
                      type="button"
                      className="border-2 border-line bg-sand px-4 py-2 text-[11px] font-bold transition-all hover:bg-paper"
                    >
                      Start Session
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Import */}
      <div>
        <div className="relative mb-4 pl-4 text-[10px] font-black uppercase tracking-[3px] text-muted">
          <span className="absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 bg-gold" />
          Import New Fixture
        </div>
        <div className="border-2 border-line bg-white p-5">
          <textarea
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            placeholder="Paste YAML fixture here..."
            rows={5}
            className="mb-3 w-full border-2 border-line bg-sand p-3 font-mono text-[12px] outline-none focus:border-indigo"
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="border-2 border-ink bg-white px-5 py-2 text-[11px] font-black transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:bg-primary hover:text-bg hover:shadow-[4px_4px_0_#F59E0B]"
            >
              Import
            </button>
            <button
              type="button"
              className="border-2 border-line bg-sand px-5 py-2 text-[11px] font-bold transition-all hover:bg-paper"
            >
              Browse File
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
