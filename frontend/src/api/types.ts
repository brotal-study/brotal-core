// Tipos del contrato v0.1 (docs/CONTRATO-V0.1.md, seccion 3).
export interface Category {
  id: string
  label: string
  color: string
}

export interface CareerCourse {
  code: string
  name: string
  credits: number
  category: string
  prerequisites: string[]
  optional?: boolean
}

export interface Semester {
  number: number
  label: string
  courses: CareerCourse[]
}

export interface CareerManifest {
  schema_version: string
  id: string
  country: string
  university: { id: string; name: string; short_name: string }
  career: { name: string; plan_year: number; plan_ref?: string; updated_at: string }
  categories: Category[]
  semesters: Semester[]
}

export interface PackMetadata {
  university_id: string
  career_ids: string[]
  created_year: number
  updated_year: number
  version: string
  authors: string[]
  license: string
  world_metaphor?: string
}

export interface PackSummary {
  id: string
  course_code: string
  title: string
  metadata: PackMetadata
  node_count: number
}

export interface CareerSummary {
  id: string
  country: string
  university: string
  university_short: string
  name: string
  plan_ref?: string
}

/** Estado del ramo en el perfil local. `active` = Cursando, `passed` = Aprobado. */
export type CourseStatus = 'pending' | 'active' | 'passed' | 'archived'

/** Ramo unificado (de la malla o agregado a mano en Modo Libre). */
export interface Course {
  id: string
  code: string
  name: string
  credits: number
  category: string
  prerequisites: string[]
  optional?: boolean
  semester: number | null
  manual?: boolean
}
