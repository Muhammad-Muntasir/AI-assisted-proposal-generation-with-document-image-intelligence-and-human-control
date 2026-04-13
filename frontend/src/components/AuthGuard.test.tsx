/**
 * Property 15: Unauthenticated access always redirects to Login
 * Validates: Requirements 1.4
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import * as fc from 'fast-check'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import AuthGuard from './AuthGuard'

// Arbitrary that generates any localStorage state that is NOT 'true'
// (covers: missing key, 'false', empty string, random strings, etc.)
const unauthenticatedState = fc.oneof(
  fc.constant(null),           // key absent
  fc.constant('false'),
  fc.constant(''),
  fc.constant('0'),
  fc.string().filter(s => s !== 'true'),
)

function renderWithRouter(isAuthValue: string | null) {
  if (isAuthValue === null) {
    localStorage.removeItem('isAuthenticated')
  } else {
    localStorage.setItem('isAuthenticated', isAuthValue)
  }

  render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/" element={<div data-testid="login-page">Login</div>} />
        <Route
          path="/dashboard"
          element={
            <AuthGuard>
              <div data-testid="dashboard-page">Dashboard</div>
            </AuthGuard>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AuthGuard — Property 15: Unauthenticated access always redirects to Login', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('redirects to Login when isAuthenticated is not set', () => {
    renderWithRouter(null)
    expect(screen.getByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument()
  })

  it('redirects to Login when isAuthenticated is "false"', () => {
    renderWithRouter('false')
    expect(screen.getByTestId('login-page')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument()
  })

  it('allows access when isAuthenticated is "true"', () => {
    renderWithRouter('true')
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument()
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  it(
    'property: any unauthenticated localStorage state always redirects to Login',
    () => {
      fc.assert(
        fc.property(unauthenticatedState, (authValue) => {
          localStorage.clear()
          renderWithRouter(authValue)

          const loginPage = screen.queryByTestId('login-page')
          const dashboardPage = screen.queryByTestId('dashboard-page')

          const redirectedToLogin = loginPage !== null
          const dashboardNotShown = dashboardPage === null

          // Clean up DOM between runs
          document.body.innerHTML = ''

          return redirectedToLogin && dashboardNotShown
        }),
        { numRuns: 50 },
      )
    },
  )
})
