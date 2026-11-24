import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GraduationCap, Compass, ArrowRight } from 'lucide-react'
import { listCareers } from '../api/curriculum'
import type { CareerSummary } from '../api/types'
import { useAppStore } from '../store/useAppStore'

type Choice = 'career' | 'free'

export default function OnboardingPage() {
  const navigate = useNavigate()
  const { profile, saveProfile } = useAppStore()
  const [name, setName] = useState(profile?.name ?? '')
  const [choice, setChoice] = useState<Choice>(profile?.mode ?? 'career')
  const [careers, setCareers] = useState<CareerSummary[]>([])
  const [careerId, setCareerId] = useState(profile?.careerId ?? '')

  useEffect(() => {
    listCareers().then((c) => {
      setCareers(c)
      setCareerId((cur) => cur || c[0]?.id || '')
    })
  }, [])

  const countries = [...new Set(careers.map((c) => c.country))]
  const country = countries[0] ?? 'CL'
  const universities = [...new Map(careers.map((c) => [c.university_short, c.university])).entries()]
  const [uni, setUni] = useState('PUCV')
  const careerOpts = careers.filter((c) => c.university_short === uni)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    saveProfile({
      name: name.trim() || 'Estudiante',
      mode: choice,
      careerId: choice === 'career' ? careerId : null,
    })
    useAppStore.getState().loadCareer().then(() => navigate('/'))
  }

  const field =
    'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900'

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-6 px-4 py-10">
      <div>
        <h1 className="text-2xl font-semibold">{profile ? 'Perfil local' : 'Bienvenido a Brotal'}</h1>
        <p className="mt-1 text-sm text-slate-500">
          Tu perfil vive solo en este dispositivo. No hay cuentas ni login.
        </p>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-5">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Nombre local
          <input className={field} value={name} onChange={(e) => setName(e.target.value)} placeholder="Como quieres que te llamemos" maxLength={40} />
        </label>

        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-medium">¿Cómo vas a estudiar?</legend>
          {(
            [
              ['career', GraduationCap, 'Mi carrera', 'Elige tu malla y sigue tu avance.'],
              ['free', Compass, 'Estudio por mi cuenta / Modo Libre', 'Agrega ramos manuales en un tablero libre.'],
            ] as const
          ).map(([val, Icon, title, desc]) => (
            <button
              key={val}
              type="button"
              onClick={() => setChoice(val)}
              aria-pressed={choice === val}
              className={`flex flex-col items-start gap-1 rounded-lg border p-4 text-left ${
                choice === val
                  ? 'border-slate-900 ring-1 ring-slate-900 dark:border-slate-100 dark:ring-slate-100'
                  : 'border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-900'
              }`}
            >
              <Icon size={20} />
              <span className="text-sm font-semibold">{title}</span>
              <span className="text-xs text-slate-500">{desc}</span>
            </button>
          ))}
        </fieldset>

        {choice === 'career' && (
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              País
              <select className={field} value={country} disabled>
                <option value={country}>{country === 'CL' ? 'Chile' : country}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Universidad
              <select className={field} value={uni} onChange={(e) => setUni(e.target.value)}>
                {universities.map(([short]) => (
                  <option key={short} value={short}>{short}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm font-medium">
              Carrera
              <select className={field} value={careerId} onChange={(e) => setCareerId(e.target.value)}>
                {careerOpts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{c.plan_ref ? ` (${c.plan_ref})` : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <button
          type="submit"
          disabled={choice === 'career' && !careerId}
          className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
        >
          {choice === 'career' ? 'Entrar a Mi Malla' : 'Entrar al tablero libre'}
          <ArrowRight size={16} />
        </button>
      </form>
    </main>
  )
}
