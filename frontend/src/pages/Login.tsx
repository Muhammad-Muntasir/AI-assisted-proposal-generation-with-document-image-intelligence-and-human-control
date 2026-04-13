import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cognitoLogin, cognitoSignUp, cognitoConfirmSignUp } from '../auth'

type Mode = 'signin' | 'signup' | 'confirm'

export default function Login() {
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (mode === 'signin') {
        await cognitoLogin(email, password)
        navigate('/dashboard')
      } else if (mode === 'signup') {
        await cognitoSignUp(email, password)
        setMode('confirm')
      } else if (mode === 'confirm') {
        await cognitoConfirmSignUp(email, code)
        setMode('signin')
        setError(null)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-100 via-purple-50 to-blue-100">
      <div className="absolute top-0 left-0 w-72 h-72 bg-purple-300 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-pulse" />
      <div className="absolute bottom-0 right-0 w-72 h-72 bg-indigo-300 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-pulse" />

      <div className="relative w-full max-w-md mx-4">
        <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-2xl shadow-indigo-200/50 border border-white/60 p-10">
          <div className="flex justify-center mb-6">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-300/50">
              <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </div>

          <h1 className="text-2xl font-bold text-gray-900 text-center mb-1">
            {mode === 'signin' ? 'Welcome back' : mode === 'signup' ? 'Create account' : 'Verify email'}
          </h1>
          <p className="text-sm text-gray-500 text-center mb-8">
            {mode === 'signin' ? 'Sign in to your proposal platform' : mode === 'signup' ? 'Register to get started' : `Enter the code sent to ${email}`}
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {mode !== 'confirm' && (
              <>
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">Email address</label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all duration-200 placeholder-gray-400"
                    required
                  />
                </div>
                <div>
                  <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
                  <input
                    id="password"
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all duration-200 placeholder-gray-400"
                    required
                  />
                  {mode === 'signup' && (
                    <p className="text-xs text-gray-400 mt-1">Min 8 chars, uppercase, lowercase, number and symbol</p>
                  )}
                </div>
              </>
            )}

            {mode === 'confirm' && (
              <div>
                <label htmlFor="code" className="block text-sm font-medium text-gray-700 mb-1.5">Verification code</label>
                <input
                  id="code"
                  type="text"
                  value={code}
                  onChange={e => setCode(e.target.value)}
                  placeholder="123456"
                  className="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all duration-200 placeholder-gray-400"
                  required
                />
              </div>
            )}

            {error && (
              <div role="alert" className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-semibold rounded-xl shadow-md shadow-indigo-300/40 hover:from-indigo-700 hover:to-purple-700 active:scale-[0.98] transition-all duration-200 mt-1 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? 'Please wait...' : mode === 'signin' ? 'Sign In' : mode === 'signup' ? 'Create Account' : 'Verify'}
            </button>
          </form>

          <div className="mt-6 text-center text-sm text-gray-500">
            {mode === 'signin' ? (
              <>Don't have an account?{' '}
                <button onClick={() => { setMode('signup'); setError(null) }} className="text-indigo-600 font-medium hover:underline">Sign up</button>
              </>
            ) : mode === 'signup' ? (
              <>Already have an account?{' '}
                <button onClick={() => { setMode('signin'); setError(null) }} className="text-indigo-600 font-medium hover:underline">Sign in</button>
              </>
            ) : (
              <button onClick={() => { setMode('signin'); setError(null) }} className="text-indigo-600 font-medium hover:underline">Back to sign in</button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
