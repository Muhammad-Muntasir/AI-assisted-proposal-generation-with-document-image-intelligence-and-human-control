import { useNavigate } from 'react-router-dom'
import { clearAuth, getCurrentUserEmail } from '../auth'

// Derive a display name from email: "munamazon0@gmail.com" → "Munamazon"
function getDisplayName(email: string): string {
  if (!email) return 'Reviewer'
  const local = email.split('@')[0]           // "munamazon0"
  const name  = local.replace(/[0-9_.-]+$/, '') // strip trailing digits/symbols
  return name.charAt(0).toUpperCase() + name.slice(1) || 'Reviewer'
}

export default function Navbar() {
  const navigate    = useNavigate()
  const email       = getCurrentUserEmail()
  const displayName = getDisplayName(email)
  const initials    = displayName.slice(0, 2).toUpperCase()

  function handleLogout() {
    clearAuth()
    navigate('/')
  }

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 shadow-sm z-20 relative">
      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}>
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <span className="text-lg font-bold text-gray-900">AI Proposal Platform</span>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-4">
        {/* Reviewer badge */}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold" style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}>
            {initials}
          </div>
          <div className="hidden sm:flex flex-col leading-tight">
            <span className="text-sm font-semibold text-gray-800">{displayName}</span>
            <span className="text-xs text-gray-400">Reviewer</span>
          </div>
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg transition-all duration-200 hover:opacity-90 active:scale-95"
          style={{ background: 'linear-gradient(135deg, #4F46E5, #06B6D4)' }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          Logout
        </button>
      </div>
    </header>
  )
}
