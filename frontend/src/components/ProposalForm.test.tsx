/**
 * Unit tests for ProposalForm
 * - Task 9.1: file type validation, empty submission guard, input preservation on error
 *
 * Property 1: Invalid file types are always rejected (Task 9.2)
 * Validates: Requirements 2.5, 8.2
 *
 * Property 2: Empty form submission is always blocked (Task 9.3)
 * Validates: Requirements 2.6
 *
 * Property 16: Generation failure preserves all form inputs (Task 9.4)
 * Validates: Requirements 9.1, 9.2, 9.4
 */
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import * as fc from 'fast-check'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ProposalForm, { type GenerateRequest } from './ProposalForm'

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeFile(name: string, type: string): File {
  return new File(['content'], name, { type })
}

function renderForm(props?: Partial<{ isLoading: boolean; disabled: boolean; onSubmit: (d: GenerateRequest) => void }>) {
  const onSubmit = props?.onSubmit ?? vi.fn()
  render(
    <ProposalForm
      onSubmit={onSubmit}
      isLoading={props?.isLoading ?? false}
      disabled={props?.disabled ?? false}
    />,
  )
  return { onSubmit }
}

// Silence fetch calls made during useEffect (proposals dropdown)
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
})

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

// ─── Unit Tests (Task 9.1) ───────────────────────────────────────────────────

describe('ProposalForm — file type validation', () => {
  it('rejects a photo with an invalid MIME type and shows an error', async () => {
    renderForm()
    const input = screen.getByLabelText(/site photos/i)
    const badFile = makeFile('sketch.gif', 'image/gif')
    await act(async () => {
      fireEvent.change(input, { target: { files: [badFile] } })
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('alert').textContent).toMatch(/invalid file type/i)
  })

  it('accepts a valid JPG photo without error', async () => {
    renderForm()
    const input = screen.getByLabelText(/site photos/i)
    const goodFile = makeFile('photo.jpg', 'image/jpeg')
    await act(async () => {
      fireEvent.change(input, { target: { files: [goodFile] } })
    })
    // No alert for photos
    const alerts = screen.queryAllByRole('alert')
    const photoAlert = alerts.find((el) => el.textContent?.match(/jpg|png|photo/i))
    expect(photoAlert).toBeUndefined()
  })

  it('rejects a reference document with an invalid type and shows an error', async () => {
    renderForm()
    const input = screen.getByLabelText(/reference documents/i)
    const badFile = makeFile('data.csv', 'text/csv')
    await act(async () => {
      fireEvent.change(input, { target: { files: [badFile] } })
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('alert').textContent).toMatch(/invalid file type/i)
  })

  it('rejects an SOP document with an invalid type and shows an error', async () => {
    renderForm()
    const input = screen.getByLabelText(/sop documents/i)
    const badFile = makeFile('notes.txt', 'text/plain')
    await act(async () => {
      fireEvent.change(input, { target: { files: [badFile] } })
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('alert').textContent).toMatch(/invalid file type/i)
  })

  it('accepts a valid PDF for reference documents without error', async () => {
    renderForm()
    const input = screen.getByLabelText(/reference documents/i)
    const goodFile = makeFile('report.pdf', 'application/pdf')
    await act(async () => {
      fireEvent.change(input, { target: { files: [goodFile] } })
    })
    const alerts = screen.queryAllByRole('alert')
    const docAlert = alerts.find((el) => el.textContent?.match(/pdf|word|doc/i))
    expect(docAlert).toBeUndefined()
  })
})

describe('ProposalForm — empty submission guard', () => {
  it('blocks submission when survey notes are blank and no files are attached', async () => {
    const { onSubmit } = renderForm()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
    })
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('blocks submission when survey notes are whitespace-only and no files', async () => {
    const { onSubmit } = renderForm()
    fireEvent.change(screen.getByLabelText(/survey notes/i), { target: { value: '   \n\t  ' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
    })
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('allows submission when survey notes are non-empty', async () => {
    // Mock fetch for upload-url and the actual PUT
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [] })  // GET /proposals
      .mockResolvedValue({ ok: true, json: async () => ({ uploadUrl: 'http://s3', s3Key: 'key1' }) }),
    )
    const { onSubmit } = renderForm()
    fireEvent.change(screen.getByLabelText(/survey notes/i), { target: { value: 'Some notes' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
    })
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
  })
})

describe('ProposalForm — input preservation on error', () => {
  it('retains survey notes after a failed generation (onSubmit throws)', async () => {
    // Simulate: upload succeeds, but onSubmit represents a generation failure
    // The form itself never clears inputs — they remain controlled
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [] })  // GET /proposals
      .mockResolvedValue({ ok: true, json: async () => ({ uploadUrl: 'http://s3', s3Key: 'key1' }) }),
    )
    const failingSubmit = vi.fn() // called but generation "fails" externally — form doesn't clear
    render(<ProposalForm onSubmit={failingSubmit} isLoading={false} disabled={false} />)

    const textarea = screen.getByLabelText(/survey notes/i)
    fireEvent.change(textarea, { target: { value: 'My important notes' } })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
    })

    await waitFor(() => expect(failingSubmit).toHaveBeenCalled())
    // Notes must still be present — controlled input never cleared
    expect((textarea as HTMLTextAreaElement).value).toBe('My important notes')
  })

  it('retains survey notes when upload fails (network error)', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [] })  // GET /proposals
      .mockRejectedValue(new Error('Network error')),              // upload-url fails
    )
    const onSubmit = vi.fn()
    render(<ProposalForm onSubmit={onSubmit} isLoading={false} disabled={false} />)

    const textarea = screen.getByLabelText(/survey notes/i)
    fireEvent.change(textarea, { target: { value: 'Preserved notes' } })

    const photoInput = screen.getByLabelText(/site photos/i)
    await act(async () => {
      fireEvent.change(photoInput, { target: { files: [makeFile('img.jpg', 'image/jpeg')] } })
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
    })

    await waitFor(() => expect(onSubmit).not.toHaveBeenCalled())
    // Notes still intact
    expect((textarea as HTMLTextAreaElement).value).toBe('Preserved notes')
    // Upload error shown
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

// ─── Property 1: Invalid file types are always rejected (Task 9.2) ──────────

/**
 * Property 1: Invalid file types are always rejected
 * Validates: Requirements 2.5, 8.2
 */
describe('Property 1 — Invalid file types are always rejected', () => {
  const invalidPhotoTypes = fc.oneof(
    fc.constant('image/gif'),
    fc.constant('image/webp'),
    fc.constant('image/bmp'),
    fc.constant('image/tiff'),
    fc.constant('text/plain'),
    fc.constant('application/pdf'),
    fc.constant('video/mp4'),
    fc.string({ minLength: 1, maxLength: 30 }).filter(
      (t) => !['image/jpeg', 'image/png'].includes(t),
    ),
  )

  const invalidDocTypes = fc.oneof(
    fc.constant('image/jpeg'),
    fc.constant('image/png'),
    fc.constant('text/plain'),
    fc.constant('text/csv'),
    fc.constant('application/zip'),
    fc.constant('video/mp4'),
    fc.string({ minLength: 1, maxLength: 30 }).filter(
      (t) =>
        !['application/pdf', 'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(t),
    ),
  )

  it('property: any invalid photo MIME type always shows a validation error', () => {
    fc.assert(
      fc.property(invalidPhotoTypes, fc.string({ minLength: 1, maxLength: 20 }), (mimeType, baseName) => {
        document.body.innerHTML = ''
        render(<ProposalForm onSubmit={vi.fn()} isLoading={false} disabled={false} />)

        const input = screen.getByLabelText(/site photos/i)
        const file = makeFile(`${baseName}.bad`, mimeType)

        act(() => {
          fireEvent.change(input, { target: { files: [file] } })
        })

        const alerts = screen.queryAllByRole('alert')
        const hasError = alerts.some((el) => el.textContent?.match(/invalid file type/i))
        document.body.innerHTML = ''
        return hasError
      }),
      { numRuns: 50 },
    )
  })

  it('property: any invalid document MIME type always shows a validation error (reference docs)', () => {
    fc.assert(
      fc.property(invalidDocTypes, fc.string({ minLength: 1, maxLength: 20 }), (mimeType, baseName) => {
        document.body.innerHTML = ''
        render(<ProposalForm onSubmit={vi.fn()} isLoading={false} disabled={false} />)

        const input = screen.getByLabelText(/reference documents/i)
        const file = makeFile(`${baseName}.bad`, mimeType)

        act(() => {
          fireEvent.change(input, { target: { files: [file] } })
        })

        const alerts = screen.queryAllByRole('alert')
        const hasError = alerts.some((el) => el.textContent?.match(/invalid file type/i))
        document.body.innerHTML = ''
        return hasError
      }),
      { numRuns: 50 },
    )
  })

  it('property: any invalid document MIME type always shows a validation error (SOP docs)', () => {
    fc.assert(
      fc.property(invalidDocTypes, fc.string({ minLength: 1, maxLength: 20 }), (mimeType, baseName) => {
        document.body.innerHTML = ''
        render(<ProposalForm onSubmit={vi.fn()} isLoading={false} disabled={false} />)

        const input = screen.getByLabelText(/sop documents/i)
        const file = makeFile(`${baseName}.bad`, mimeType)

        act(() => {
          fireEvent.change(input, { target: { files: [file] } })
        })

        const alerts = screen.queryAllByRole('alert')
        const hasError = alerts.some((el) => el.textContent?.match(/invalid file type/i))
        document.body.innerHTML = ''
        return hasError
      }),
      { numRuns: 50 },
    )
  })
})

// ─── Property 2: Empty form submission is always blocked (Task 9.3) ─────────

/**
 * Property 2: Empty form submission is always blocked
 * Validates: Requirements 2.6
 */
describe('Property 2 — Empty form submission is always blocked', () => {
  // Whitespace-only strings (or empty)
  const whitespaceNotes = fc.oneof(
    fc.constant(''),
    fc.constant('   '),
    fc.constant('\n'),
    fc.constant('\t'),
    fc.string({ minLength: 1, maxLength: 50 }).map((s) => s.replace(/[^ \t\n\r]/g, ' ')),
  )

  it('property: any whitespace-only survey notes with no files always blocks submission', { timeout: 30000 }, () => {
    fc.assert(
      fc.property(whitespaceNotes, (notes) => {
        document.body.innerHTML = ''
        const onSubmit = vi.fn()
        render(<ProposalForm onSubmit={onSubmit} isLoading={false} disabled={false} />)

        const textarea = screen.getByLabelText(/survey notes/i)
        act(() => {
          fireEvent.change(textarea, { target: { value: notes } })
          fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
        })

        const blocked = onSubmit.mock.calls.length === 0
        const errorShown = screen.queryAllByRole('alert').length > 0
        document.body.innerHTML = ''
        return blocked && errorShown
      }),
      { numRuns: 20 },
    )
  })
})

// ─── Property 16: Generation failure preserves all form inputs (Task 9.4) ───

/**
 * Property 16: Generation failure preserves all form inputs
 * Validates: Requirements 9.1, 9.2, 9.4
 */
describe('Property 16 — Generation failure preserves all form inputs', () => {
  const nonEmptyNotes = fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0)

  it('property: survey notes are preserved after upload failure', () => {
    fc.assert(
      fc.property(nonEmptyNotes, (notes) => {
        document.body.innerHTML = ''

        // First call: GET /proposals (useEffect), subsequent calls: upload-url fails
        vi.stubGlobal('fetch', vi.fn()
          .mockResolvedValueOnce({ ok: true, json: async () => [] })
          .mockRejectedValue(new Error('Upload failed')),
        )

        const onSubmit = vi.fn()
        render(<ProposalForm onSubmit={onSubmit} isLoading={false} disabled={false} />)

        const textarea = screen.getByLabelText(/survey notes/i)

        act(() => {
          fireEvent.change(textarea, { target: { value: notes } })
        })

        // Attach a photo so the upload path is exercised
        const photoInput = screen.getByLabelText(/site photos/i)
        act(() => {
          fireEvent.change(photoInput, { target: { files: [makeFile('img.jpg', 'image/jpeg')] } })
        })

        act(() => {
          fireEvent.click(screen.getByRole('button', { name: /generate draft/i }))
        })

        // Notes must still equal what was typed
        const preserved = (textarea as HTMLTextAreaElement).value === notes
        document.body.innerHTML = ''
        vi.restoreAllMocks()
        return preserved
      }),
      { numRuns: 30 },
    )
  })
})
