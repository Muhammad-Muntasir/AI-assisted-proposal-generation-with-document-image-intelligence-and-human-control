import { useState } from 'react'
import type { ReactElement } from 'react'

interface Section {
  sectionName: string
  content: string
  rationale: string
}

interface DraftRecord {
  proposalId: string
  status: string
  aiGeneratedSections: Section[]
  rationale: Record<string, string>
  createdAt: string
  version: number
}

interface DraftOutputProps {
  draft: DraftRecord | null
  error: string | null
  onApprove: (sections: Section[]) => void
  onRetry: () => void
}

interface SectionState {
  edited: string
  original: string
  isEditing: boolean
}

const SECTION_ICONS: Record<string, ReactElement> = {
  'Executive Summary': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  ),
  'Scope of Work': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
    </svg>
  ),
  'Timeline': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  ),
  'Budget Estimate': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  'Methodology': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
    </svg>
  ),
  'Assumptions & Exclusions': (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
}

export default function DraftOutput({ draft, error, onApprove, onRetry }: DraftOutputProps) {
  const [sectionStates, setSectionStates] = useState<Record<string, SectionState>>({})
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})

  function getState(section: Section): SectionState {
    return sectionStates[section.sectionName] ?? {
      edited: section.content, original: section.content, isEditing: false,
    }
  }

  function toggleExpand(name: string) {
    setExpandedSections(prev => ({ ...prev, [name]: !prev[name] }))
  }

  function startEdit(sectionName: string, currentContent: string) {
    setSectionStates(prev => ({
      ...prev,
      [sectionName]: { ...(prev[sectionName] ?? { original: currentContent }), edited: prev[sectionName]?.edited ?? currentContent, isEditing: true },
    }))
    setExpandedSections(prev => ({ ...prev, [sectionName]: true }))
  }

  function saveEdit(sectionName: string) {
    setSectionStates(prev => ({ ...prev, [sectionName]: { ...prev[sectionName], isEditing: false } }))
  }

  function updateEdited(sectionName: string, value: string) {
    setSectionStates(prev => ({ ...prev, [sectionName]: { ...prev[sectionName], edited: value } }))
  }

  function handleApprove() {
    if (!draft) return
    const finalSections: Section[] = draft.aiGeneratedSections.map(s => ({
      sectionName: s.sectionName,
      content: sectionStates[s.sectionName]?.edited ?? s.content,
      rationale: s.rationale,
    }))
    onApprove(finalSections)
  }

  // Empty state
  if (!draft && !error) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 h-full flex flex-col items-center justify-center p-10 text-center min-h-[400px]">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 bg-gray-100">
          <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <h3 className="text-base font-semibold text-gray-700 mb-1">No Draft Yet</h3>
        <p className="text-sm text-gray-400 max-w-xs">Fill in the survey notes on the left and click Generate Draft to create an AI-powered proposal.</p>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-red-200 p-6" role="alert">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-red-100 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-red-700">Generation Failed</p>
            <p className="text-sm text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-xl transition-all hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 flex flex-col">
      {/* Panel header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}>
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">AI Draft</h2>
            <p className="text-xs text-gray-500">Review and edit before approving</p>
          </div>
        </div>
        {/* Status badge */}
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          Draft
        </span>
      </div>

      {/* Sections */}
      <div className="p-4 space-y-3 overflow-y-auto flex-1">
        {draft!.aiGeneratedSections.map((section, idx) => {
          const state = getState(section)
          const isExpanded = expandedSections[section.sectionName] ?? true
          const isEdited = state.edited !== state.original

          return (
            <div
              key={`${section.sectionName}-${idx}`}
              className="border border-gray-200 rounded-xl overflow-hidden transition-all duration-200"
              data-testid={`section-${section.sectionName}`}
            >
              {/* Section header */}
              <div
                className="flex items-center justify-between px-4 py-3 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors"
                onClick={() => toggleExpand(section.sectionName)}
              >
                <div className="flex items-center gap-2.5">
                  <span className="w-5 h-5 rounded-md flex items-center justify-center text-indigo-600 bg-indigo-100">
                    {SECTION_ICONS[section.sectionName] ?? <span className="text-xs font-bold">{idx + 1}</span>}
                  </span>
                  <span className="text-sm font-semibold text-gray-800">{section.sectionName}</span>
                  {isEdited && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">Edited</span>
                  )}
                </div>
                <svg
                  className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </div>

              {/* Section body */}
              {isExpanded && (
                <div className="px-4 py-3 space-y-3">
                  {state.isEditing ? (
                    <div>
                      <textarea
                        aria-label={`Edit ${section.sectionName}`}
                        className="w-full p-3 border border-indigo-300 rounded-xl text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 min-h-[120px] resize-none transition-all"
                        value={state.edited}
                        onChange={e => updateEdited(section.sectionName, e.target.value)}
                      />
                      <button
                        onClick={() => saveEdit(section.sectionName)}
                        className="mt-2 px-4 py-1.5 text-xs font-semibold text-white rounded-lg transition-all hover:opacity-90"
                        style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}
                      >
                        Save
                      </button>
                    </div>
                  ) : (
                    <div>
                      <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{state.edited}</p>
                      <button
                        onClick={() => startEdit(section.sectionName, section.content)}
                        className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                        Edit
                      </button>
                    </div>
                  )}

                  {/* Rationale */}
                  <div className="flex items-start gap-2 p-3 bg-indigo-50/60 rounded-xl border border-indigo-100">
                    <svg className="w-3.5 h-3.5 text-indigo-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p className="text-xs text-indigo-600 leading-relaxed">
                      <span className="font-semibold">Rationale: </span>{section.rationale}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Approve button */}
      <div className="px-4 pb-4 pt-2 border-t border-gray-100">
        <button
          onClick={handleApprove}
          className="w-full flex items-center justify-center gap-2 py-3 px-6 text-sm font-semibold text-white rounded-xl shadow-md transition-all duration-200 hover:opacity-90 active:scale-[0.98]"
          style={{ background: 'linear-gradient(135deg, #10B981, #06B6D4)' }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Approve & Save
        </button>
      </div>
    </div>
  )
}
