/**
 * Property 14: Invalid credentials always produce an error without navigation
 * Validates: Requirements 1.3
 */
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import * as fc from 'fast-check'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import Login from './Login'

const VALID_EMAIL = 'muhammadmuntasir2001@gmail.com'
const VALID_PASSWORD = 'M123'

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/dashboard" element={<div data-testid="dashboard-page">Dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

// Arbitrary: any (email, password) pair that is NOT the valid credential pair.
// Both fields must be non-empty so the HTML `required` constraint is satisfied
// and the form actually submits (allowing the JS validation logic to run).
const invalidCredentials = fc
  .tuple(
    fc.string({ minLength: 1 }),
    fc.string({ minLength: 1 }),
  )
  .filter(([email, password]) => !(email === VALID_EMAIL && password === VALID_PASSWORD))

describe('Login — Property 14: Invalid credentials always produce an error without navigation', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('shows error on wrong email', async () => {
    renderLogin()
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'wrong@example.com' } })
      fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'password123' } })
      fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument()
  })

  it('shows error on wrong password', async () => {
    renderLogin()
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: VALID_EMAIL } })
      fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrongpassword' } })
      fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument()
  })

  it('navigates to dashboard on valid credentials', async () => {
    renderLogin()
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: VALID_EMAIL } })
      fireEvent.change(screen.getByLabelText(/password/i), { target: { value: VALID_PASSWORD } })
      fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    })
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it(
    'property: any invalid (email, password) pair always shows error and never navigates',
    { timeout: 30000 },
    () => {
      fc.assert(
        fc.property(invalidCredentials, ([email, password]) => {
          localStorage.clear()
          document.body.innerHTML = ''

          renderLogin()

          act(() => {
            fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: email } })
            fireEvent.change(screen.getByLabelText(/password/i), { target: { value: password } })
            // Submit the form element directly to bypass HTML5 constraint validation
            // and exercise our JS credential-checking logic
            const form = document.querySelector('form')!
            fireEvent.submit(form)
          })

          const errorShown = screen.queryByRole('alert') !== null
          const dashboardNotShown = screen.queryByTestId('dashboard-page') === null

          return errorShown && dashboardNotShown
        }),
        { numRuns: 25 },
      )
    },
  )
})
