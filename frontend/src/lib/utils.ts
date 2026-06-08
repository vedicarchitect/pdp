import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Days until expiry, floored to 0. expiryDate must be YYYY-MM-DD (local date). */
export function computeDTE(expiryDate: string): number {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  // Parse as local date (not UTC) to avoid timezone-offset off-by-one
  const [y, m, d] = expiryDate.split('-').map(Number)
  const expiry = new Date(y, m - 1, d)
  const msPerDay = 1000 * 60 * 60 * 24
  return Math.max(0, Math.floor((expiry.getTime() - today.getTime()) / msPerDay))
}
