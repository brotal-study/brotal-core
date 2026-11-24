import type { Category, Course, CourseStatus } from '../api/types'

export type StatusMap = Record<string, CourseStatus>

export const statusOf = (statuses: StatusMap, id: string): CourseStatus => statuses[id] ?? 'pending'

export const missingPrereqs = (c: Course, statuses: StatusMap): string[] =>
  c.prerequisites.filter((p) => statusOf(statuses, p) !== 'passed')

export function categoryColor(categories: Category[], id: string): string {
  return categories.find((c) => c.id === id)?.color ?? '#64748b'
}

export function progress(courses: Course[], statuses: StatusMap) {
  const req = courses.filter((c) => !c.optional)
  const passed = req.filter((c) => statusOf(statuses, c.id) === 'passed')
  const credits = req.reduce((a, c) => a + c.credits, 0)
  const creditsPassed = passed.reduce((a, c) => a + c.credits, 0)
  return {
    total: req.length,
    passed: passed.length,
    credits,
    creditsPassed,
    pct: credits ? Math.round((creditsPassed / credits) * 100) : 0,
  }
}
