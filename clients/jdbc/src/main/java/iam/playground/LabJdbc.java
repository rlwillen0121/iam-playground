package iam.playground;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * pgJDBC client for legacy_app application accounts.
 * Connects with DriverManager. Not an HTTP shim.
 */
public final class LabJdbc implements AutoCloseable {
    private static final String STATUS_ACTIVE = "active";
    private static final String STATUS_DISABLED = "disabled";
    private static final String OP_CREATE = "create";
    private static final String OP_UPDATE = "update";
    private static final String OP_DISABLE = "disable";
    private static final String OP_GRANT = "grant";
    private static final String OP_REVOKE = "revoke";

    private static final String ACCOUNT_COLUMNS =
            "SELECT a.id, a.login, a.employee_ref, a.status, a.display_name, r.name AS role_name "
                    + "FROM legacy_app.accounts AS a "
                    + "LEFT JOIN legacy_app.account_roles AS ar ON ar.account_id = a.id "
                    + "LEFT JOIN legacy_app.roles AS r ON r.id = ar.role_id ";

    private final Connection connection;
    private final boolean owned;

    public LabJdbc(String url, String user, String password) throws SQLException {
        this(DriverManager.getConnection(
                Objects.requireNonNull(url, "url"),
                Objects.requireNonNull(user, "user"),
                password), true);
    }

    public LabJdbc(Connection connection) {
        this(Objects.requireNonNull(connection, "connection"), false);
    }

    private LabJdbc(Connection connection, boolean owned) {
        this.connection = connection;
        this.owned = owned;
    }

    public record Account(
            UUID id,
            String login,
            String employeeRef,
            String status,
            String displayName,
            List<String> roles) {
    }

    public List<Account> aggregateAccounts() throws SQLException {
        List<Account> accounts = new ArrayList<>();
        inTransaction(true, () -> {
            try (PreparedStatement statement = this.connection.prepareStatement(
                    ACCOUNT_COLUMNS + "ORDER BY a.login, r.name")) {
                try (ResultSet rows = statement.executeQuery()) {
                    accounts.addAll(readAccounts(rows));
                }
            }
        });
        return List.copyOf(accounts);
    }

    public UUID createAccount(String login, String employeeRef, String displayName) throws SQLException {
        Objects.requireNonNull(login, "login");
        UUID id = UUID.randomUUID();
        inTransaction(false, () -> {
            insertAccount(this.connection, id, login, employeeRef, STATUS_ACTIVE, displayName);
            insertEvent(this.connection, id, OP_CREATE);
        });
        return id;
    }

    public void updateAccount(UUID id, String login, String employeeRef, String displayName)
            throws SQLException {
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(login, "login");
        inTransaction(false, () -> {
            try (PreparedStatement statement = this.connection.prepareStatement(
                    "UPDATE legacy_app.accounts "
                            + "SET login = ?, employee_ref = ?, display_name = ? "
                            + "WHERE id = ?")) {
                setText(statement, 1, login);
                setText(statement, 2, employeeRef);
                setText(statement, 3, displayName);
                setUuid(statement, 4, id);
                requireOne(statement.executeUpdate(), "account not found");
            }
            insertEvent(this.connection, id, OP_UPDATE);
        });
    }

    public void disableAccount(UUID id) throws SQLException {
        Objects.requireNonNull(id, "id");
        inTransaction(false, () -> {
            try (PreparedStatement statement = this.connection.prepareStatement(
                    "UPDATE legacy_app.accounts SET status = ? WHERE id = ?")) {
                setText(statement, 1, STATUS_DISABLED);
                setUuid(statement, 2, id);
                requireOne(statement.executeUpdate(), "account not found");
            }
            insertEvent(this.connection, id, OP_DISABLE);
        });
    }

    public void grantRole(UUID accountId, String roleName) throws SQLException {
        Objects.requireNonNull(accountId, "accountId");
        Objects.requireNonNull(roleName, "roleName");
        inTransaction(false, () -> {
            insertRoleGrant(this.connection, accountId, roleName);
            insertEvent(this.connection, accountId, OP_GRANT);
        });
    }

    public void revokeRole(UUID accountId, String roleName) throws SQLException {
        Objects.requireNonNull(accountId, "accountId");
        Objects.requireNonNull(roleName, "roleName");
        inTransaction(false, () -> {
            try (PreparedStatement statement = this.connection.prepareStatement(
                    "DELETE FROM legacy_app.account_roles "
                            + "WHERE account_id = ? "
                            + "AND role_id = (SELECT id FROM legacy_app.roles WHERE name = ?)")) {
                setUuid(statement, 1, accountId);
                setText(statement, 2, roleName);
                requireOne(statement.executeUpdate(), "role grant not found");
            }
            insertEvent(this.connection, accountId, OP_REVOKE);
        });
    }

    public Account readAccount(UUID id) throws SQLException {
        Objects.requireNonNull(id, "id");
        List<Account> accounts = new ArrayList<>();
        inTransaction(true, () -> {
            try (PreparedStatement statement = this.connection.prepareStatement(
                    ACCOUNT_COLUMNS + "WHERE a.id = ? ORDER BY r.name")) {
                setUuid(statement, 1, id);
                try (ResultSet rows = statement.executeQuery()) {
                    accounts.addAll(readAccounts(rows));
                }
            }
        });
        if (accounts.isEmpty()) {
            return null;
        }
        return accounts.get(0);
    }

    // The missing-role failure is expected. Roll back and return; do not commit.
    public void rollbackProof(Connection connection) throws SQLException {
        Objects.requireNonNull(connection, "connection");
        if (!connection.getAutoCommit()) {
            throw new SQLException("rollbackProof requires an autocommit connection");
        }
        connection.setAutoCommit(false);
        try {
            UUID accountId = UUID.randomUUID();
            insertAccount(
                    connection,
                    accountId,
                    "rollback-" + accountId,
                    null,
                    STATUS_ACTIVE,
                    "rollback proof");
            try {
                insertRoleGrant(connection, accountId, "missing-" + accountId);
            } catch (SQLException invalidGrant) {
                if (!isInvalidRoleGrant(invalidGrant)) {
                    throw invalidGrant;
                }
                connection.rollback();
                return;
            }
            connection.rollback();
            throw new SQLException("invalid role grant did not fail");
        } catch (SQLException ex) {
            rollbackQuiet(connection, ex);
            throw ex;
        } finally {
            restoreAutoCommit(connection);
        }
    }

    @Override
    public void close() throws SQLException {
        if (owned) {
            connection.close();
        }
    }

    private void inTransaction(boolean readOnly, SqlWork work) throws SQLException {
        if (!this.connection.getAutoCommit()) {
            throw new SQLException("connection must be in autocommit mode");
        }
        boolean previousReadOnly = this.connection.isReadOnly();
        this.connection.setAutoCommit(false);
        try {
            if (readOnly) {
                this.connection.setReadOnly(true);
            }
            work.run();
            this.connection.commit();
        } catch (SQLException ex) {
            rollbackQuiet(this.connection, ex);
            throw ex;
        } catch (RuntimeException ex) {
            rollbackQuiet(this.connection, ex);
            throw ex;
        } finally {
            restoreAutoCommit(this.connection);
            if (this.connection.isReadOnly() != previousReadOnly) {
                this.connection.setReadOnly(previousReadOnly);
            }
        }
    }

    private static void insertAccount(
            Connection connection,
            UUID id,
            String login,
            String employeeRef,
            String status,
            String displayName) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO legacy_app.accounts (id, login, employee_ref, status, display_name) "
                        + "VALUES (?, ?, ?, ?, ?)")) {
            setUuid(statement, 1, id);
            setText(statement, 2, login);
            setText(statement, 3, employeeRef);
            setText(statement, 4, status);
            setText(statement, 5, displayName);
            statement.executeUpdate();
        }
    }

    private static void insertEvent(Connection connection, UUID accountId, String op) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO legacy_app.change_events (account_id, op, at) "
                        + "VALUES (?, ?, CURRENT_TIMESTAMP)")) {
            setUuid(statement, 1, accountId);
            setText(statement, 2, op);
            statement.executeUpdate();
        }
    }

    private static void insertRoleGrant(Connection connection, UUID accountId, String roleName)
            throws SQLException {
        UUID roleId = findRoleId(connection, roleName);
        if (roleId == null) {
            // Not a stored role, so account_roles_role_fk rejects the grant.
            roleId = unusedRoleId(connection);
        }
        try (PreparedStatement statement = connection.prepareStatement(
                "INSERT INTO legacy_app.account_roles (account_id, role_id) VALUES (?, ?)")) {
            setUuid(statement, 1, accountId);
            setUuid(statement, 2, roleId);
            statement.executeUpdate();
        }
    }

    private static UUID findRoleId(Connection connection, String roleName) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT id FROM legacy_app.roles WHERE name = ?")) {
            setText(statement, 1, roleName);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    return null;
                }
                return rows.getObject(1, UUID.class);
            }
        }
    }

    private static UUID unusedRoleId(Connection connection) throws SQLException {
        for (int attempt = 0; attempt < 2; attempt++) {
            UUID roleId = UUID.randomUUID();
            try (PreparedStatement statement = connection.prepareStatement(
                    "SELECT 1 FROM legacy_app.roles WHERE id = ?")) {
                setUuid(statement, 1, roleId);
                try (ResultSet rows = statement.executeQuery()) {
                    if (!rows.next()) {
                        return roleId;
                    }
                }
            }
        }
        throw new SQLException("could not choose a missing role id");
    }

    private static List<Account> readAccounts(ResultSet rows) throws SQLException {
        List<Account> accounts = new ArrayList<>();
        UUID currentId = null;
        String login = null;
        String employeeRef = null;
        String status = null;
        String displayName = null;
        List<String> roles = new ArrayList<>();
        while (rows.next()) {
            UUID id = rows.getObject("id", UUID.class);
            if (currentId == null || !currentId.equals(id)) {
                if (currentId != null) {
                    accounts.add(account(currentId, login, employeeRef, status, displayName, roles));
                }
                currentId = id;
                login = rows.getString("login");
                employeeRef = rows.getString("employee_ref");
                status = rows.getString("status");
                displayName = rows.getString("display_name");
                roles = new ArrayList<>();
            }
            String roleName = rows.getString("role_name");
            if (roleName != null) {
                roles.add(roleName);
            }
        }
        if (currentId != null) {
            accounts.add(account(currentId, login, employeeRef, status, displayName, roles));
        }
        return accounts;
    }

    private static Account account(
            UUID id,
            String login,
            String employeeRef,
            String status,
            String displayName,
            List<String> roles) {
        return new Account(id, login, employeeRef, status, displayName, List.copyOf(roles));
    }

    private static boolean isInvalidRoleGrant(SQLException error) {
        SQLException current = error;
        while (current != null) {
            String state = current.getSQLState();
            // 23503 foreign_key_violation, 23514 check_violation.
            if ("23503".equals(state) || "23514".equals(state)) {
                return true;
            }
            current = current.getNextException();
        }
        return false;
    }

    private static void requireOne(int count, String message) throws SQLException {
        if (count != 1) {
            throw new SQLException(message);
        }
    }

    private static void setText(PreparedStatement statement, int index, String value) throws SQLException {
        if (value == null) {
            statement.setNull(index, Types.VARCHAR);
        } else {
            statement.setString(index, value);
        }
    }

    private static void setUuid(PreparedStatement statement, int index, UUID value) throws SQLException {
        statement.setObject(index, Objects.requireNonNull(value, "uuid"));
    }

    private static void rollbackQuiet(Connection connection, Throwable cause) {
        try {
            if (!connection.getAutoCommit()) {
                connection.rollback();
            }
        } catch (SQLException rollbackFailure) {
            cause.addSuppressed(rollbackFailure);
        }
    }

    // pgJDBC commits inside setAutoCommit(true) when a transaction is still open.
    // Roll back first so restoring autocommit cannot commit.
    private static void restoreAutoCommit(Connection connection) throws SQLException {
        if (connection.getAutoCommit()) {
            return;
        }
        connection.rollback();
        connection.setAutoCommit(true);
    }

    @FunctionalInterface
    private interface SqlWork {
        void run() throws SQLException;
    }
}
