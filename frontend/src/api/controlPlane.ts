import { request } from './client';
import type { ControlPlaneSnapshot } from '../types/controlPlane';

export const getControlPlane = () => request<ControlPlaneSnapshot>('/api/control-plane');
