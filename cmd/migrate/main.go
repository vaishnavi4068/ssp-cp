package main

import (
	"database/sql"
	"log"
	"os"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"
)

func main() {
	if len(os.Args) < 2 {
		log.Fatal("usage: migrate up|down|status")
	}
	dsn := os.Getenv("SSP_DATABASE_URL")
	if dsn == "" {
		log.Fatal("SSP_DATABASE_URL is required")
	}
	dir := os.Getenv("SSP_MIGRATIONS_DIR")
	if dir == "" {
		dir = "db/migrations"
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer func() {
		if cerr := db.Close(); cerr != nil {
			log.Println(cerr)
		}
	}()
	if err := goose.SetDialect("postgres"); err != nil {
		log.Fatal(err)
	}
	switch os.Args[1] {
	case "up":
		err = goose.Up(db, dir)
	case "down":
		err = goose.Down(db, dir)
	case "status":
		err = goose.Status(db, dir)
	default:
		log.Fatalf("unknown command %q", os.Args[1])
	}
	if err != nil {
		log.Fatal(err)
	}
}
