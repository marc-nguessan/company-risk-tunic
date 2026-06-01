import { type FormEvent, useState } from 'react';
import type { CompanyQuery } from '../types';

interface Props {
  onSubmit: (query: CompanyQuery) => void;
  disabled?: boolean;
}

export function SearchBar({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState('');

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;

    // Heuristic: 8-digit string → registration number, otherwise name
    const isRegNumber = /^\d{8}$/.test(trimmed) || /^[A-Z]{2}\d{6}$/.test(trimmed);
    const query: CompanyQuery = isRegNumber
      ? { registration_number: trimmed }
      : { company_name: trimmed };
    onSubmit(query);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Company name or registration number"
        disabled={disabled}
        style={{ flex: 1, padding: '0.5rem 0.75rem', fontSize: '1rem' }}
      />
      <button type="submit" disabled={disabled || !value.trim()}>
        Assess
      </button>
    </form>
  );
}
