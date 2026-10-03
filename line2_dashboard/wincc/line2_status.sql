/*
  Line-2 tool status, written by the WinCC V7.5 VBScript (Line2_SyncToolStatus)
  and read by the Line-2 dashboard (config.ini: [MAIN] source = wincc).

  Run once in SSMS against Industry4_157 on the Line-2 SQL Server (172.25.208.39,49561).
  Safe to re-run: tables are only created if missing, procedures are replaced.

  Tables
    Line2_Tool_Status      one row per station + tool, always the latest values (small, fast to read)
    Line2_Tool_Log         one row per change, for traceability per MAT (purge old rows, see bottom)
    Line2_Writer_Heartbeat one row; WinCC touches it every ~30 s so the dashboard can tell
                           "WinCC script stopped" apart from "nothing changed"
*/

IF OBJECT_ID('dbo.Line2_Tool_Status', 'U') IS NULL
CREATE TABLE dbo.Line2_Tool_Status (
    StationNumber INT           NOT NULL,
    Tool          VARCHAR(16)   NOT NULL,          -- T1, T2, ...
    ToolName      NVARCHAR(100) NULL,              -- "SG Tightening"
    TorqueNm      DECIMAL(9, 2) NULL,
    SetCount      INT           NULL,
    ActualCount   INT           NULL,
    Status        VARCHAR(10)   NULL,              -- 'OK' / 'NOT OK' / NULL (unknown)
    Mode          VARCHAR(10)   NULL,              -- 'ACTIVE' / 'BYPASS' / NULL
    MAT_Number    VARCHAR(40)   NULL,              -- vehicle at the station when this was written
    VC_Number     VARCHAR(40)   NULL,
    UpdatedAt     DATETIME2(0)  NOT NULL CONSTRAINT DF_Line2_Tool_Status_UpdatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT PK_Line2_Tool_Status PRIMARY KEY (StationNumber, Tool)
);
GO

IF OBJECT_ID('dbo.Line2_Tool_Log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Line2_Tool_Log (
        Id            BIGINT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_Line2_Tool_Log PRIMARY KEY,
        LoggedAt      DATETIME2(0)  NOT NULL CONSTRAINT DF_Line2_Tool_Log_LoggedAt DEFAULT SYSDATETIME(),
        StationNumber INT           NOT NULL,
        Tool          VARCHAR(16)   NOT NULL,
        SetCount      INT           NULL,
        ActualCount   INT           NULL,
        Status        VARCHAR(10)   NULL,
        Mode          VARCHAR(10)   NULL,
        MAT_Number    VARCHAR(40)   NULL,
        VC_Number     VARCHAR(40)   NULL
    );
    CREATE INDEX IX_Line2_Tool_Log_MAT ON dbo.Line2_Tool_Log (MAT_Number, LoggedAt);
END
GO

IF OBJECT_ID('dbo.Line2_Writer_Heartbeat', 'U') IS NULL
CREATE TABLE dbo.Line2_Writer_Heartbeat (
    Id       TINYINT      NOT NULL CONSTRAINT PK_Line2_Writer_Heartbeat PRIMARY KEY
                                   CONSTRAINT CK_Line2_Writer_Heartbeat_One CHECK (Id = 1),
    LastSeen DATETIME2(0) NOT NULL
);
GO

CREATE OR ALTER PROCEDURE dbo.usp_Line2_UpsertTool
    @Station     INT,
    @Tool        VARCHAR(16),
    @ToolName    NVARCHAR(100) = NULL,
    @TorqueNm    DECIMAL(9, 2) = NULL,
    @SetCount    INT           = NULL,
    @ActualCount INT           = NULL,
    @Status      VARCHAR(10)   = NULL,
    @Mode        VARCHAR(10)   = NULL,
    @MAT         VARCHAR(40)   = NULL,
    @VC          VARCHAR(40)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE dbo.Line2_Tool_Status
       SET ToolName = @ToolName, TorqueNm = @TorqueNm, SetCount = @SetCount, ActualCount = @ActualCount,
           Status = @Status, Mode = @Mode, MAT_Number = @MAT, VC_Number = @VC, UpdatedAt = SYSDATETIME()
     WHERE StationNumber = @Station AND Tool = @Tool;

    IF @@ROWCOUNT = 0
        INSERT INTO dbo.Line2_Tool_Status
            (StationNumber, Tool, ToolName, TorqueNm, SetCount, ActualCount, Status, Mode, MAT_Number, VC_Number)
        VALUES (@Station, @Tool, @ToolName, @TorqueNm, @SetCount, @ActualCount, @Status, @Mode, @MAT, @VC);

    INSERT INTO dbo.Line2_Tool_Log (StationNumber, Tool, SetCount, ActualCount, Status, Mode, MAT_Number, VC_Number)
    VALUES (@Station, @Tool, @SetCount, @ActualCount, @Status, @Mode, @MAT, @VC);
END
GO

CREATE OR ALTER PROCEDURE dbo.usp_Line2_Heartbeat
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE dbo.Line2_Writer_Heartbeat SET LastSeen = SYSDATETIME() WHERE Id = 1;
    IF @@ROWCOUNT = 0
        INSERT INTO dbo.Line2_Writer_Heartbeat (Id, LastSeen) VALUES (1, SYSDATETIME());
END
GO

/*
  Least-privilege login for the WinCC script: it can ONLY run the two procedures above
  (the procedures write the tables through ownership chaining). Run as sysadmin once,
  with your own password:

  CREATE LOGIN line2_writer WITH PASSWORD = 'Choose-A-Strong-Password', CHECK_POLICY = ON;
  CREATE USER  line2_writer FOR LOGIN line2_writer;
  GRANT EXECUTE ON dbo.usp_Line2_UpsertTool TO line2_writer;
  GRANT EXECUTE ON dbo.usp_Line2_Heartbeat  TO line2_writer;

  Housekeeping for the history table, e.g. as a nightly SQL Agent job (keeps 90 days):

  DELETE FROM dbo.Line2_Tool_Log WHERE LoggedAt < DATEADD(DAY, -90, SYSDATETIME());

  Traceability: every change for one vehicle
  SELECT * FROM dbo.Line2_Tool_Log WHERE MAT_Number = 'MAT513357TFJ12781' ORDER BY LoggedAt;
*/
