"use client";

import { useState } from "react";
import { useAuth } from "@/providers/AuthProvider";
import { useUsers, useAddUser, useUpdateRole, useToggleApproval, useDeleteUser, useRunAssignment } from "@/hooks/useUsers";
import { ROLE_LABELS } from "@/lib/constants";
import type { User } from "@/lib/types";

const ALL_ROLES = ["lead", "tenured_operator", "new_operator"];

export default function UsersPage() {
  const { isLead, user: currentUser } = useAuth();
  const { data: users, isLoading } = useUsers();
  const addUser = useAddUser();
  const updateRole = useUpdateRole();
  const toggleApproval = useToggleApproval();
  const deleteUser = useDeleteUser();
  const runAssignment = useRunAssignment();

  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("tenured_operator");
  const [newReduction, setNewReduction] = useState(20);

  const [editEmail, setEditEmail] = useState("");
  const [editRole, setEditRole] = useState("");
  const [editReduction, setEditReduction] = useState(0);

  const [assignResult, setAssignResult] = useState<any>(null);

  if (!isLead) return <div className="text-gray-400 p-8">Lead access required.</div>;

  const userList: User[] = users || [];
  const selectedUser = userList.find((u) => u.email === editEmail);

  async function handleAddUser() {
    if (!newEmail || !newName) return;
    await addUser.mutateAsync({ email: newEmail.trim(), name: newName.trim(), role: newRole, reduction_pct: newRole === "new_operator" ? newReduction : 0 });
    setNewEmail("");
    setNewName("");
  }

  async function handleUpdateRole() {
    if (!editEmail) return;
    await updateRole.mutateAsync({ email: editEmail, role: editRole, reduction_pct: editRole === "new_operator" ? editReduction : 0 });
  }

  async function handleRunAssignment() {
    setAssignResult(null);
    const result = await runAssignment.mutateAsync(true);
    setAssignResult(result);
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Manage Users</h1>

      {/* Metrics */}
      {userList.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-[#262730] rounded-lg p-4">
            <p className="text-sm text-gray-400">Total Users</p>
            <p className="text-2xl font-bold">{userList.length}</p>
          </div>
          <div className="bg-[#262730] rounded-lg p-4">
            <p className="text-sm text-gray-400">Leads</p>
            <p className="text-2xl font-bold">{userList.filter((u) => u.role === "lead").length}</p>
          </div>
          <div className="bg-[#262730] rounded-lg p-4">
            <p className="text-sm text-gray-400">Tenured</p>
            <p className="text-2xl font-bold">{userList.filter((u) => u.role === "tenured_operator").length}</p>
          </div>
          <div className="bg-[#262730] rounded-lg p-4">
            <p className="text-sm text-gray-400">New Operators</p>
            <p className="text-2xl font-bold">{userList.filter((u) => u.role === "new_operator").length}</p>
          </div>
        </div>
      )}

      {/* Users table */}
      {isLoading ? (
        <div className="animate-pulse bg-[#262730] rounded-lg h-48" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-[#262730] text-gray-400 sticky top-0">
              <tr>
                <th className="text-left px-4 py-3">Email</th>
                <th className="text-left px-4 py-3">Name</th>
                <th className="text-left px-4 py-3">Role</th>
                <th className="text-left px-4 py-3">Reduction</th>
                <th className="text-left px-4 py-3">Access</th>
                <th className="text-left px-4 py-3">Added By</th>
              </tr>
            </thead>
            <tbody>
              {userList.map((u) => (
                <tr key={u.email} className="border-t border-gray-800 hover:bg-[#262730]/50">
                  <td className="px-4 py-3 font-medium">{u.email}</td>
                  <td className="px-4 py-3">{u.name}</td>
                  <td className="px-4 py-3 text-gray-400">{ROLE_LABELS[u.role] || u.role}</td>
                  <td className="px-4 py-3 text-gray-400">{u.role === "new_operator" ? `${u.reduction_pct}%` : "—"}</td>
                  <td className="px-4 py-3">{u.approved ? <span className="text-green-400">Active</span> : <span className="text-red-400">Revoked</span>}</td>
                  <td className="px-4 py-3 text-gray-400">{u.added_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add + Edit side by side */}
      <div className="grid grid-cols-2 gap-6">
        {/* Add user */}
        <div className="bg-[#262730] rounded-lg p-5">
          <h3 className="font-semibold mb-4">Add New User</h3>
          <div className="space-y-3">
            <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="email@example.com"
              className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Full name"
              className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)}
              className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm">
              {ALL_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
            {newRole === "new_operator" && (
              <div>
                <label className="text-xs text-gray-400">Reduction %</label>
                <input type="number" value={newReduction} onChange={(e) => setNewReduction(Number(e.target.value))}
                  min={0} max={90} step={5}
                  className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
              </div>
            )}
            <button onClick={handleAddUser} disabled={addUser.isPending}
              className="w-full bg-[#FF4B4B] hover:bg-[#E04343] text-white rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 cursor-pointer">
              {addUser.isPending ? "Adding..." : "Add User"}
            </button>
          </div>
        </div>

        {/* Edit user */}
        <div className="bg-[#262730] rounded-lg p-5">
          <h3 className="font-semibold mb-4">Edit Existing User</h3>
          <div className="space-y-3">
            <select value={editEmail} onChange={(e) => {
              setEditEmail(e.target.value);
              const u = userList.find((u) => u.email === e.target.value);
              if (u) { setEditRole(u.role); setEditReduction(u.reduction_pct); }
            }} className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm">
              <option value="">Select user</option>
              {userList.map((u) => <option key={u.email} value={u.email}>{u.email}</option>)}
            </select>
            {selectedUser && (
              <>
                <p className="text-xs text-gray-400">Current: {ROLE_LABELS[selectedUser.role]} · Approved: {selectedUser.approved ? "Yes" : "No"}</p>
                <select value={editRole} onChange={(e) => setEditRole(e.target.value)}
                  className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm">
                  {ALL_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                </select>
                {editRole === "new_operator" && (
                  <input type="number" value={editReduction} onChange={(e) => setEditReduction(Number(e.target.value))}
                    min={0} max={90} step={5}
                    className="w-full bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm" />
                )}
                <div className="flex gap-2">
                  <button onClick={handleUpdateRole} disabled={updateRole.isPending}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-3 py-2 text-sm disabled:opacity-50 cursor-pointer">
                    Update Role
                  </button>
                  <button onClick={() => toggleApproval.mutate({ email: editEmail, approved: !selectedUser.approved })}
                    className={`flex-1 ${selectedUser.approved ? "bg-gray-600 hover:bg-gray-700" : "bg-green-600 hover:bg-green-700"} text-white rounded-lg px-3 py-2 text-sm cursor-pointer`}>
                    {selectedUser.approved ? "Revoke" : "Approve"}
                  </button>
                  {editEmail !== currentUser?.email && (
                    <button onClick={() => { if (confirm(`Delete ${editEmail}?`)) deleteUser.mutate(editEmail); }}
                      className="bg-red-600 hover:bg-red-700 text-white rounded-lg px-3 py-2 text-sm cursor-pointer">
                      Delete
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Assignment trigger */}
      <div className="bg-[#262730] rounded-lg p-5">
        <h3 className="font-semibold mb-2">Run Assignment Engine</h3>
        <p className="text-sm text-gray-400 mb-4">Normally runs at 8 AM daily. Use this to trigger manually.</p>
        <button onClick={handleRunAssignment} disabled={runAssignment.isPending}
          className="bg-[#FF4B4B] hover:bg-[#E04343] text-white rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 cursor-pointer">
          {runAssignment.isPending ? "Running..." : "Run Assignment Now"}
        </button>
        {assignResult && (
          <div className="mt-4 bg-[#0E1117] rounded-lg p-3 text-sm">
            {assignResult.error ? (
              <p className="text-red-400">{assignResult.error}</p>
            ) : (
              <p className="text-green-400">Assigned {assignResult.assigned} reviews to {assignResult.operators} operators</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
